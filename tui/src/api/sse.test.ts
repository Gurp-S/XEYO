/**
 * TUI 流式层的回归测试（node --test + tsx，不引新依赖）。
 * 钉住三件真实数据上会错的事：并行同名工具的结果配对、缺字段的用量不得当成 0、
 * 以及 SSE 分块边界（一行被切断 / 一个中文被切断）。
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  applyXy,
  deltaText,
  interruptSession,
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
    'data: {"choices":[{"delta":{"content":"A"}}]}\n\ndata: {"choices":[{"delta":{"content":"B"}}]}\n\n';
  const { deltas, state } = await collectStream(payload, [20]);
  assert.equal(deltas.join(""), "AB");
  assert.equal(state.done, 1);
  assert.equal(state.error, "");
});

test("中文正好被切在字节边界时不丢字", async () => {
  const payload = 'data: {"choices":[{"delta":{"content":"压缩中"}}]}\n\n';
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

// --------------------------------------------------------------------------- //
// 送达回执：resolvePermission / interruptSession 必须把非 2xx 变成 reject。
// 这两个 helper 曾经是文件里唯二不查 res.ok 的 —— await 完就把 Response 丢掉，
// 于是 403/404/422 一律"成功"，App 照常写下 ✓ allowed（授权面上的假回执）。
// --------------------------------------------------------------------------- //

function fetchReturning(status: number) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fake = (async (input: unknown, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return { ok: status >= 200 && status < 300, status, json: async () => ({}) } as never;
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
  const { fake, calls } = fetchReturning(200);
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
