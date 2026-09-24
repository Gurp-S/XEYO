/**
 * 授权帧解析的回归（node --test + tsx，不引新依赖）。
 *
 * 钉住的是授权面上最贵的一类错：**没有 request_id 也开弹窗**。
 * 以前 App 用 `String(xy.request_id ?? "")` 兜底，于是畸形帧照样弹出面板，
 * 用户按 a/d/r 之后往 /v1/permission/resolve 发一个空 request_id，
 * 屏幕已经写下 "✓ allowed"，而服务端从头到尾没收到过这次决议。
 */
import assert from "node:assert/strict";
import test from "node:test";

import { parsePermissionPending } from "./permissionPrompt.js";

test("带 request_id 的帧正常开弹窗，字段原样带出", () => {
  const frame = parsePermissionPending({
    type: "permission_pending",
    request_id: "req_7",
    tool_name: "Bash",
    prompt: "要执行 rm -rf 吗",
  });
  assert.equal(frame.kind, "open");
  if (frame.kind !== "open") return;
  assert.deepEqual(frame.prompt, {
    requestId: "req_7",
    tool: "Bash",
    prompt: "要执行 rm -rf 吗",
  });
});

test("缺 request_id（缺失 / 空 / 纯空白）一律判为不可决议，绝不发空 id", () => {
  for (const xy of [
    { tool_name: "Bash" },
    { request_id: "", tool_name: "Bash" },
    { request_id: "   ", tool_name: "Bash" },
    { request_id: null, tool_name: "Bash" },
    {},
  ]) {
    const frame = parsePermissionPending(xy);
    assert.equal(frame.kind, "unresolvable", JSON.stringify(xy));
    if (frame.kind === "unresolvable") {
      assert.match(frame.detail, /request_id/);
    }
  }
});

test("工具名缺失不影响决议能力，但要显式标出未知而不是空白卡片", () => {
  const frame = parsePermissionPending({ request_id: "req_7" });
  assert.equal(frame.kind, "open");
  if (frame.kind !== "open") return;
  assert.equal(frame.prompt.requestId, "req_7");
  assert.notEqual(frame.prompt.tool.trim(), "");
});

test("reason 是 prompt 的合法别名（服务端两种都发过）", () => {
  const frame = parsePermissionPending({
    request_id: "r",
    tool_name: "Write",
    reason: "路径在工作区外",
  });
  assert.equal(frame.kind, "open");
  if (frame.kind !== "open") return;
  assert.equal(frame.prompt.prompt, "路径在工作区外");
});

test("prompt 为空时留空串，不写出 undefined 字样", () => {
  const frame = parsePermissionPending({ request_id: "r", tool_name: "Read" });
  assert.equal(frame.kind, "open");
  if (frame.kind !== "open") return;
  assert.equal(frame.prompt.prompt, "");
});
