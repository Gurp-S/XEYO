/**
 * TUI 流式层的回归测试（node --test + tsx，不引新依赖）。
 * 钉住四件真实数据上会错的事：并行同名工具的结果配对、缺字段的用量不得当成 0、
 * SSE 分块边界（一行被切断 / 一个中文被切断），以及会话面 200 回执的形状
 * （缺 sessions 不能说成「没有可恢复的会话」，缺 messages 不能说成空历史，
 * 服务端报的读取降级必须显示出来）。
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  applyXy,
  createSession,
  DecisionNotApplied,
  decisionRetainsPrompt,
  deltaText,
  getSessionMessages,
  interruptSession,
  listSessions,
  parseCreatedSession,
  parseLoadedSession,
  parseSessionList,
  parseSlashResponse,
  resolveAsk,
  resolvePermission,
  streamChat,
  type ChatBody,
  type SseHandlers,
} from "./sse.js";
import type { TimelineItem } from "../types.js";

let seq = 0;
const nextId = () => `i${++seq}`;

function toolItems(items: TimelineItem[]) {
  return items.filter((it) => it.kind === "tool") as Extract<
    TimelineItem,
    { kind: "tool" }
  >[];
}

function twoReadCalls() {
  let items: TimelineItem[] = [];
  items = applyXy(items, { type: "tool_call", name: "Read", tool_use_id: "c1", input: { file_path: "a.ts" } }, nextId);
  items = applyXy(items, { type: "tool_call", name: "Read", tool_use_id: "c2", input: { file_path: "b.ts" } }, nextId);
  return items;
}

test("结果按调用顺序回来时也必须各归各卡（按名字匹配会贴错）", () => {
  let items = twoReadCalls();
  assert.equal(toolItems(items).length, 2);
  items = applyXy(items, { type: "tool_result", name: "Read", tool_use_id: "c1", output: "aaa" }, nextId);
  items = applyXy(items, { type: "tool_result", name: "Read", tool_use_id: "c2", output: "B-B-B" }, nextId);

  const tools = toolItems(items);
  assert.equal(tools[0]!.toolUseId, "c1");
  assert.equal(tools[0]!.result, "aaa");
  assert.equal(tools[1]!.toolUseId, "c2");
  assert.equal(tools[1]!.result, "B-B-B");
});

test("结果乱序回来（后发的先完成）时同样各归各卡", () => {
  let items = twoReadCalls();
  items = applyXy(items, { type: "tool_result", name: "Read", tool_use_id: "c2", output: "B-B-B" }, nextId);
  items = applyXy(items, { type: "tool_result", name: "Read", tool_use_id: "c1", output: "aaa" }, nextId);

  const tools = toolItems(items);
  assert.deepEqual(tools.map((t) => t.status), ["completed", "completed"]);
  assert.equal(tools[0]!.result, "aaa");
  assert.equal(tools[1]!.result, "B-B-B");
});

test("旧流没有身份时退回最早一条同名在跑的卡", () => {
  let items: TimelineItem[] = [];
  items = applyXy(items, { type: "tool_call", name: "Bash", input: { command: "one" } }, nextId);
  items = applyXy(items, { type: "tool_call", name: "Bash", input: { command: "two" } }, nextId);
  items = applyXy(items, { type: "tool_result", name: "Bash", output: "1st" }, nextId);
  const tools = toolItems(items);
  assert.equal(tools[0]!.status, "completed");
  assert.equal(tools[0]!.result, "1st");
  assert.equal(tools[1]!.status, "running");
});

test("结果没有对应卡片时补一条，不静默丢弃", () => {
  const items = applyXy([], { type: "tool_result", name: "Grep", tool_use_id: "ghost", output: "x", is_error: true }, nextId);
  const tools = toolItems(items);
  assert.equal(tools.length, 1);
  assert.equal(tools[0]!.status, "error");
  assert.equal(tools[0]!.isError, true);
});

test("结果带着一个对不上的 id 时，绝不许贴到同名在跑的卡上", () => {
  // 身份已知且查无此卡 ⇒ 只能补新卡。以前 findToolIndex 在 id 查不到时会继续
  // 走"同名 + 最早在跑"的兜底，于是这条结果把别人的卡结掉了，而真正的调用
  // 永远停在 running —— 名字兜底只该服务于"整条流都没有身份"的旧流。
  let items = twoReadCalls();
  items = applyXy(items, { type: "tool_result", name: "Read", tool_use_id: "ghost", output: "ORPHAN" }, nextId);

  const tools = toolItems(items);
  assert.equal(tools.length, 3, "孤儿结果应另开一条卡");
  assert.equal(tools[0]!.toolUseId, "c1");
  assert.equal(tools[0]!.status, "running", "c1 被一个对不上号的结果结掉了");
  assert.equal(tools[1]!.toolUseId, "c2");
  assert.equal(tools[1]!.status, "running");
  assert.equal(tools[2]!.result, "ORPHAN");
});

test("tool_progress 带着对不上的 id 时只能丢弃，不能改别人的卡", () => {
  let items = twoReadCalls();
  items = applyXy(items, { type: "tool_progress", name: "Read", tool_use_id: "ghost", message: "半路" }, nextId);
  const tools = toolItems(items);
  assert.equal(tools.length, 2);
  assert.equal(tools[0]!.progress, undefined);
  assert.equal(tools[1]!.progress, undefined);
});

test("缺字段的用量不得变成 0", () => {
  let items: TimelineItem[] = [{ id: nextId(), kind: "assistant", text: "hi" }];
  items = applyXy(items, { type: "usage", completion_tokens: 7 }, nextId);
  const first = items[0];
  assert.equal(first?.kind, "assistant");
  const usage = first && first.kind === "assistant" ? first.usage : undefined;
  assert.equal(usage?.completionTokens, 7);
  assert.equal(usage?.promptTokens, undefined);
});

test("tool_progress 只更新对应卡片", () => {
  let items: TimelineItem[] = [];
  items = applyXy(items, { type: "tool_call", name: "Bash", tool_use_id: "p1" }, nextId);
  items = applyXy(items, { type: "tool_call", name: "Bash", tool_use_id: "p2" }, nextId);
  items = applyXy(items, { type: "tool_progress", name: "Bash", tool_use_id: "p2", message: "step 2" }, nextId);
  const tools = toolItems(items);
  assert.equal(tools[0]!.progress, undefined);
  assert.equal(tools[1]!.progress, "step 2");
});

/** 把一段 SSE 文本按指定字节位置切开喂给 streamChat（复现真实的分块边界）。 */
function fakeFetchAt(text: string, cuts: number[]) {
  const bytes = new TextEncoder().encode(text);
  const parts: Uint8Array[] = [];
  let prev = 0;
  for (const c of [...cuts, bytes.length]) {
    if (c > prev) {
      parts.push(bytes.slice(prev, c));
      prev = c;
    }
  }
  let i = 0;
  return async () => ({
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () =>
          i < parts.length ? { done: false, value: parts[i++] } : { done: true, value: undefined },
      }),
    },
  });
}

function collector() {
  const deltas: string[] = [];
  const xy: Record<string, unknown>[] = [];
  const state = { done: 0, error: "" as string };
  const handlers: SseHandlers = {
    onDelta: (t) => deltas.push(t),
    onXy: (e) => xy.push(e),
    onDone: () => {
      state.done += 1;
    },
    onError: (e) => {
      state.error = e.message;
    },
  };
  return { deltas, xy, state, handlers };
}

const BODY: ChatBody = {
  model: "m",
  stream: true,
  session_id: "s",
  provider: "deepseek",
  messages: [{ role: "user", content: "hi" }],
};

async function collectStream(text: string, cuts: number[]) {
  const { deltas, xy, state, handlers } = collector();
  const original = globalThis.fetch;
  globalThis.fetch = fakeFetchAt(text, cuts) as never;
  try {
    await streamChat("http://x", "", BODY, handlers);
  } finally {
    globalThis.fetch = original;
  }
  return { deltas, xy, state };
}

test("一行 data 被切在两个分块里也不丢事件", async () => {
  const payload =
    'data: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: {"choices":[{"delta":{"content":"B"}}]}\n\ndata: [DONE]\n\n';
  const { deltas, state } = await collectStream(payload, [20]);
  assert.equal(deltas.join(""), "AB");
  assert.equal(state.done, 1);
  assert.equal(state.error, "");
});

test("中文正好被切在字节边界时不丢字", async () => {
  const payload = 'data: {"choices":[{"delta":{"content":"压缩中"}}]}\n\ndata: [DONE]\n\n';
  const bytes = Buffer.from(payload, "utf8");
  const start = bytes.indexOf(Buffer.from("压缩中", "utf8"));
  assert.ok(start > 0, "样例里应含多字节正文");
  // 切在第一个汉字中间：不 flush 解码器就会吃掉半个字符。
  const { deltas, state } = await collectStream(payload, [start + 1]);
  assert.equal(deltas.join(""), "压缩中");
  assert.equal(state.done, 1);
});

test("deltaText 忽略没有正文的帧", () => {
  assert.equal(deltaText({ choices: [{ delta: {} }] }), "");
  assert.equal(deltaText({ choices: [] }), "");
  assert.equal(deltaText({}), "");
  assert.equal(deltaText({ choices: [{ delta: { content: 1 } }] }), "");
});

test("空响应和未完成断流走错误出口", async () => {
  for (const payload of ['', 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n']) {
    const {state} = await collectStream(payload, []);
    assert.equal(state.done, 0);
    assert.match(state.error, /incomplete_stream/);
  }
});

test("完成标记可拆分且末尾无需换行", async () => {
  const payload = 'data: [DONE]';
  const {state} = await collectStream(payload, [8, 10]);
  assert.equal(state.done, 1);
  assert.equal(state.error, '');
});

test("完成标记无需等待 EOF，并释放流 reader", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n'));},
    cancel() {cancelled = true;},
  });
  const c = collector();
  await withFetch((async () => new Response(body)) as never, () => streamChat('http://x', '', BODY, c.handlers));
  assert.equal(c.state.done, 1);
  assert.equal(cancelled, true);
});

test("主动取消保留收尾语义；非主动 AbortError 走错误出口", async () => {
  for (const aborted of [true, false]) {
    const ac = new AbortController();
    if (aborted) ac.abort();
    const body = new ReadableStream<Uint8Array>({start(controller) {controller.error(new DOMException('read aborted', 'AbortError'));}});
    const c = collector();
    await withFetch((async () => new Response(body)) as never, () => streamChat('http://x', '', BODY, c.handlers, ac.signal));
    assert.equal(c.state.done, aborted ? 1 : 0);
    assert.equal(c.state.error, aborted ? '' : 'read aborted');
  }
});

// --------------------------------------------------------------------------- //
// 送达回执：resolvePermission / interruptSession 必须把非 2xx 变成 reject。
// 这两个 helper 曾经是文件里唯二不查 res.ok 的 —— await 完就把 Response 丢掉，
// 于是 403/404/422 一律"成功"，App 照常写下 ✓ allowed（授权面上的假回执）。
// --------------------------------------------------------------------------- //

function fetchReturning(status: number, payload: unknown = {}) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fake = (async (input: unknown, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => payload,
    } as never;
  }) as never;
  return { fake, calls };
}

async function withFetch<T>(fake: never, body: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = fake;
  try {
    return await body();
  } finally {
    globalThis.fetch = original;
  }
}

test("决议被服务端拒绝时必须 reject，而不是静默算成功", async () => {
  const { fake, calls } = fetchReturning(403);
  await assert.rejects(
    withFetch(fake, () => resolvePermission("http://127.0.0.1:1", "k", "req_1", "allow")),
    /403/,
  );
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/v1\/permission\/resolve$/);
});

test("决议成功时 resolve，并把 choice 映射成 approved + outcome", async () => {
  // 200 信封里必须带 ok:true —— 这正是新契约要求客户端读的那一层。
  const { fake, calls } = fetchReturning(200, { ok: true, request_id: "req_1", grant_id: "" });
  await withFetch(fake, () => resolvePermission("http://x/", "k", "req_1", "deny"));
  const sent = JSON.parse(String(calls[0].init?.body));
  assert.equal(sent.request_id, "req_1");
  assert.equal(sent.approved, false);
  assert.equal(sent.outcome, "deny");
  // 尾斜杠必须被剥掉，否则会打到 /v1//permission… 这种双斜杠路径。
  assert.ok(!calls[0].url.includes("x//"));
});

test("中断请求失败时必须 reject，调用方才能说「服务端未确认」", async () => {
  const { fake } = fetchReturning(500);
  await assert.rejects(
    withFetch(fake, () => interruptSession("http://127.0.0.1:1", "", "sess_1")),
    /500/,
  );
});

// --------------------------------------------------------------------------- //
// 200 信封里的拒绝：/v1/permission/resolve 与 /v1/interrupt 用 {ok:false}
// 表达"送达了但没接受"，只看 res.ok 会把它写成 ✓ allowed / 已中断。
// --------------------------------------------------------------------------- //

test("200 + ok:false(already_resolved) 必须 reject 并带上 reason", async () => {
  const { fake } = fetchReturning(200, { ok: false, reason: "already_resolved" });
  const e = await withFetch(fake, () =>
    resolvePermission("http://x/", "k", "req_1", "allow"),
  ).catch((err: unknown) => err);
  assert.ok(e instanceof DecisionNotApplied, String(e));
  assert.equal((e as DecisionNotApplied).reason, "already_resolved");
  assert.match((e as DecisionNotApplied).message, /已在别处答复/);
});

test("200 + ok:false(no_such_request) 说清挂起项已不在", async () => {
  const { fake } = fetchReturning(200, { ok: false, reason: "no_such_request" });
  await assert.rejects(
    withFetch(fake, () => resolvePermission("http://x/", "", "req_1", "deny")),
    /挂起项已不在服务端/,
  );
});

test("200 但信封里没有 ok 字段 = 读不出，不得算成功", async () => {
  const { fake } = fetchReturning(200, { request_id: "req_1" });
  const e = await withFetch(fake, () =>
    resolvePermission("http://x/", "", "req_1", "allow"),
  ).catch((err: unknown) => err);
  assert.ok(e instanceof DecisionNotApplied);
  assert.equal((e as DecisionNotApplied).reason, "");
});

test("中断：200 + ok:false 也要 reject，调用方才不会说服务端已停", async () => {
  const { fake } = fetchReturning(200, { ok: false });
  await assert.rejects(
    withFetch(fake, () => interruptSession("http://x/", "", "sess_1")),
  );
});

test("中断成功（200 + ok:true）不 reject", async () => {
  const { fake } = fetchReturning(200, { ok: true });
  await withFetch(fake, () => interruptSession("http://x/", "", "sess_1"));
});

// --------------------------------------------------------------------------- //
// 会话面四个 helper 过去是裸转型：只查 HTTP 状态，不看 200 的正文。
// 于是"200 但读不出"被写成正面事实 —— /load 说「没有可恢复的会话」、
// 拿 undefined 当 session_id 继续发请求、读坏的历史显示成完整历史。
// 好形体取自 python/server/routers/sessions.py 的真实返回。
// --------------------------------------------------------------------------- //

test("会话列表缺 sessions 不得变成「没有可恢复的会话」", async () => {
  assert.throws(() => parseSessionList({}), /没有可恢复的会话/);
  assert.throws(() => parseSessionList(null), /回执不是对象/);
  assert.deepEqual(parseSessionList({ sessions: [] }), []);
});

test("会话列表里的条目必须真是会话（缺 id 会渲染成空白行）", () => {
  assert.deepEqual(
    parseSessionList({ sessions: [{ id: "s1", title: "T", createdAt: 1, updatedAt: 2 }] }),
    [{ id: "s1", title: "T", createdAt: 1, updatedAt: 2 }],
  );
  assert.throws(() => parseSessionList({ sessions: [{ title: "没有 id" }] }), /不是会话/);
});

test("新建会话拿不到服务端签发的 id 就失败，不自造一个", () => {
  assert.throws(() => parseCreatedSession({ ok: true, cwd: "D:/p" }), /session_id/);
  assert.throws(() => parseCreatedSession({ ok: true, session_id: "  ", cwd: "D:/p" }), /session_id/);
  assert.throws(() => parseCreatedSession({ ok: false, session_id: "x", cwd: "" }), /没有接受/);
  // cwd 可以是空串：那表示这个会话还没绑工作区，是一个事实而不是缺失。
  assert.deepEqual(parseCreatedSession({ ok: true, session_id: "xeyo-1", cwd: "" }), {
    session_id: "xeyo-1",
    cwd: "",
  });
});

test("载入历史：缺 messages 不等于这个会话没有消息", () => {
  assert.throws(
    () => parseLoadedSession({ session_id: "s1", cwd: "D:/p" }),
    /这个会话没有消息/,
  );
  assert.throws(() => parseLoadedSession({ session_id: "", cwd: "D:/p", messages: [] }), /session_id/);
  // 老服务端不认 cwd 时也不能悄悄沿用旧工作区：这一栏读不出就要报错。
  assert.throws(() => parseLoadedSession({ session_id: "s1", messages: [] }), /session_id \/ messages \/ cwd/);
});

test("服务端报了读取降级，载入说明就必须带上", () => {
  const clean = parseLoadedSession({ session_id: "s1", cwd: "D:/p", messages: [{ id: "m1", role: "user", text: "hi", createdAt: 1 }] });
  assert.equal(clean.incomplete, undefined);
  assert.equal(clean.messages.length, 1);

  const degraded = parseLoadedSession({
    session_id: "s1",
    cwd: "D:/p",
    messages: [],
    degraded: true,
    read_errors: [{ path: "a.jsonl", error: "boom" }, { path: "b.jsonl", error: "boom" }],
    skipped_lines: 7,
  });
  assert.equal(degraded.incomplete, "服务端读取降级 · 跳过 7 行 · 2 处读取失败");
});

test("helper 真的走了解析：200 空体不会给出可用的 session_id", async () => {
  const { fake } = fetchReturning(200, { ok: true, cwd: "D:/p" });
  await assert.rejects(
    withFetch(fake, () => createSession("http://x/", "", undefined)),
    /session_id/,
  );
});

test("helper 真的走了解析：缺 sessions 的 200 会 reject 给 /load 的 catch", async () => {
  const { fake } = fetchReturning(200, {});
  await assert.rejects(withFetch(fake, () => listSessions("http://x/", "")), /没有可恢复的会话/);
});

test("helper 真的走了解析：缺 messages 的 200 不得变成一份空历史", async () => {
  const { fake } = fetchReturning(200, { session_id: "s1", cwd: "D:/p" });
  await assert.rejects(
    withFetch(fake, () => getSessionMessages("http://x/", "", "s1")),
    /这个会话没有消息/,
  );
});

test("非 200 要带上服务端给的原因，而不是只剩一个状态码", async () => {
  const { fake } = fetchReturning(404, {
    detail: { message: "no transcript for session: sess_typo", type: "transcript_not_found" },
  });
  await assert.rejects(
    withFetch(fake, () => getSessionMessages("http://x/", "", "sess_typo")),
    /HTTP 404 · no transcript for session: sess_typo/,
  );
});

test("斜杠命令：缺 handled 就是读不出服务端有没有接这个命令", () => {
  assert.throws(() => parseSlashResponse({ message: "ok" }), /handled/);
  assert.deepEqual(parseSlashResponse({ handled: false, kind: "unknown", message: "未知命令", result: null }), {
    handled: false,
    kind: "unknown",
    message: "未知命令",
    result: null,
  });
});

test("决议未生效后的弹窗保留：already_resolved 之外都可重试", () => {
  // 别处已经答过 ⇒ 本端收场（弹窗不回来，也不需要回来）。
  assert.equal(decisionRetainsPrompt(new DecisionNotApplied("already_resolved", "")), false);
  // 未送达（网络 / HTTP 5xx）与未被接受（no_such_request / 无 reason）：保留弹窗可重试。
  // 此前 App 把这些也一丢：唯一作答入口消失，而服务端可能还在等这单决议。
  assert.equal(decisionRetainsPrompt(new DecisionNotApplied("no_such_request", "")), true);
  assert.equal(decisionRetainsPrompt(new DecisionNotApplied("", "")), true);
  assert.equal(decisionRetainsPrompt(new Error("HTTP 500")), true);
  assert.equal(decisionRetainsPrompt(new TypeError("fetch failed")), true);
});

test("忙时 202 受理体走 onAccepted，不进流消费（#2）", async () => {
  const seen: unknown[] = [];
  const fake = (async () =>
    new Response(
      JSON.stringify({
        queued: true,
        delivery: "after_turn",
        queue_id: "q1",
        position: 2,
      }),
      { status: 202, headers: { "content-type": "application/json" } },
    )) as never;
  await withFetch(fake, () =>
    streamChat("http://x", "", BODY, {
      onDelta: () => {
        throw new Error("受理体不该被当流（不该有 delta）");
      },
      onXy: () => {},
      onDone: () => {
        throw new Error("受理体不该被当流（不该有 done）");
      },
      onError: (e) => {
        throw e;
      },
      onAccepted: (p) => seen.push(p),
    }),
  );
  assert.equal(seen.length, 1);
  assert.deepEqual(seen[0], {
    queued: true,
    delivery: "after_turn",
    queue_id: "q1",
    position: 2,
  });
});

test("受理体无人处理时必须出声，不静默挂起", async () => {
  let err: Error | null = null;
  const fake = (async () =>
    new Response(JSON.stringify({ queued: true }), {
      status: 202,
      headers: { "content-type": "application/json" },
    })) as never;
  await withFetch(fake, () =>
    streamChat("http://x", "", BODY, {
      onDelta: () => {},
      onXy: () => {},
      onDone: () => {},
      onError: (e) => {
        err = e;
      },
    }),
  );
  assert.ok(err && /受理/.test((err as Error).message));
});

test("resolveAsk：非 2xx 必须 reject（不静默算成功）", async () => {
  const { fake } = fetchReturning(403);
  await assert.rejects(
    withFetch(fake, () => resolveAsk("http://127.0.0.1:1", "k", "req_1", "甲")),
    /403/,
  );
});

test("resolveAsk：200 信封 ok:false 判「未接受」（already_resolved 可识别）", async () => {
  const { fake } = fetchReturning(200, {
    ok: false,
    request_id: "req_1",
    reason: "already_resolved",
  });
  await assert.rejects(
    withFetch(fake, () => resolveAsk("http://x/", "", "req_1", "甲")),
    (e: unknown) =>
      e instanceof DecisionNotApplied && e.reason === "already_resolved",
  );
});

test("resolveAsk：ok:true 才 resolve，且 actor=tui", async () => {
  const { fake, calls } = fetchReturning(200, { ok: true, request_id: "req_1" });
  await withFetch(fake, () => resolveAsk("http://x/", "", "req_1", "42"));
  const sent = JSON.parse(String((calls[0] as { init?: RequestInit }).init?.body));
  assert.deepEqual(sent, { request_id: "req_1", answer: "42", actor: "tui" });
});
