/**
 * 无头 `--json` 的 fail-closed 契约：没有 TTY 时默认拒绝，但"拒绝"必须真的回到
 * 服务端——只在本地宣布会让服务端那一轮挂在等决议上，quality gate 就变成挂死。
 */
import assert from "node:assert/strict";
import test from "node:test";

import { runJsonChat } from "./runJson.js";
import type { CliConfig } from "./types.js";

const CONFIG: CliConfig = {
  baseUrl: "http://127.0.0.1:9",
  apiKey: "",
  provider: "deepseek",
  model: "deepseek-chat",
  cwd: "/tmp",
  sessionId: "sess-headless",
  agentMode: "agent",
  permissionMode: "risk",
  demo: false,
};

function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(frames.join(""));
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
}

const PERMITTED_FRAMES = [
  'data: {"xy":{"type":"permission_pending","request_id":"apr1","tool_name":"Bash","prompt":"rm -rf build"}}\n\n',
  'data: {"choices":[{"delta":{"content":"停下了"}}]}\n\n',
  'data: [DONE]\n\n',
];

test('空响应或部分输出后断流的 JSON 退出码非零，不能输出成功', async () => {
  for (const frames of [[], ['data: {"choices":[{"delta":{"content":"partial"}}]}\n\n']]) {
    const originalFetch = globalThis.fetch;
    const originalWrite = process.stdout.write;
    const lines: string[] = [];
    globalThis.fetch = (async (input: unknown) => String(input).endsWith('/health')
      ? {ok: true, status: 200, json: async () => ({})}
      : new Response(sseBody(frames))) as never;
    // 只捕获应用 JSON，转发 node:test 的二进制报告，避免把测试结果本身吞掉。
    process.stdout.write = ((chunk: string | Uint8Array, ...args: unknown[]) => {
      if (typeof chunk === 'string' && chunk.startsWith('{')) {lines.push(chunk); return true;}
      return Reflect.apply(originalWrite, process.stdout, [chunk, ...args]);
    }) as never;
    let code: number;
    try {code = await runJsonChat(CONFIG, 'sample');}
    finally {globalThis.fetch = originalFetch; process.stdout.write = originalWrite;}
    assert.equal(code, 1);
    const events = lines.flatMap(line => line.trim().split('\n').map(value => JSON.parse(value)));
    assert.ok(events.some(event => event.type === 'error' && /incomplete_stream/.test(event.message)));
    assert.ok(!events.some(event => event.type === 'done' && event.ok === true));
  }
});

test("permission_pending 会把拒绝发回服务端，并且退出码非零", async () => {
  const calls: {url: string; body: unknown}[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.endsWith("/health")) {
      return { ok: true, status: 200, json: async () => ({}) } as never;
    }
    if (url.endsWith("/permission/resolve")) {
      return { ok: true, status: 200, json: async () => ({}) } as never;
    }
    return {
      ok: true,
      status: 200,
      body: sseBody(PERMITTED_FRAMES),
      json: async () => ({}),
    } as never;
  }) as never;

  const lines: string[] = [];
  const write = process.stdout.write.bind(process.stdout);
  process.stdout.write = ((chunk: string | Uint8Array, ...args: unknown[]) => {
    if (typeof chunk === 'string' && chunk.startsWith('{')) {lines.push(chunk); return true;}
    return Reflect.apply(write, process.stdout, [chunk, ...args]);
  }) as never;

  let code = 0;
  try {
    code = await runJsonChat(CONFIG, "删掉 build 目录");
    // 决议是 fire-and-forget：给它一个 tick 落地（真实进程里由事件循环保证）。
    await new Promise((r) => setTimeout(r, 20));
  } finally {
    (process.stdout as unknown as { write: typeof write }).write = write;
    globalThis.fetch = original;
  }

  const events = lines
    .join("")
    .split("\n")
    .filter((l) => l.startsWith('{"type":'))
    .map((l) => JSON.parse(l) as Record<string, unknown>);
  const denied = events.find((e) => e.type === "permission_denied");
  assert.ok(denied, `应发出 permission_denied，实际：${JSON.stringify(events)}`);
  const resolved = calls.find((c) => c.url.endsWith("/permission/resolve"));
  assert.ok(resolved, "拒绝必须回给服务端，否则那一轮会一直等决议");
  assert.deepEqual(resolved!.body, {
    request_id: "apr1",
    approved: false,
    outcome: "deny",
    actor: "tui",
  });
  assert.equal(code, 1);
  assert.deepEqual(
    events.find((e) => e.type === "done"),
    { type: "done", ok: false },
  );
});

test("没有正文的提示词直接失败，不碰网络", async () => {
  const original = globalThis.fetch;
  let touched = 0;
  globalThis.fetch = (async () => {
    touched += 1;
    return { ok: true, status: 200, json: async () => ({}) } as never;
  }) as never;
  try {
    assert.equal(await runJsonChat(CONFIG, "   "), 2);
  } finally {
    globalThis.fetch = original;
  }
  assert.equal(touched, 0);
});
