/**
 * `permission_pending` 帧 → 可决议的弹窗。纯函数，方便用真实/畸形帧直接喂测。
 *
 * 存在的理由：服务端帧的 `request_id` 是弹窗能否被决议的唯一凭据。以前 App 用
 * `String(xy.request_id ?? "")` 兜底，于是缺字段时照样开弹窗，用户按下 a/d/r
 * 之后往 `/v1/permission/resolve` 发一个空 request_id —— 屏幕已经写下
 * "✓ allowed"，而服务端从来没收到过这一次决议。那是**假回执**，而且发生在授权面。
 * 现在：没有 request_id 就不开弹窗（否则会把用户锁在一个无法决议的面板上），
 * 只回一条中性事实；工具名缺失不影响决议，仍开弹窗但显式标出未知。
 */
import type { PermissionPrompt } from "../types.js";

export type PermissionFrame =
  | { kind: "open"; prompt: PermissionPrompt }
  | { kind: "unresolvable"; detail: string };

const TOOL_UNKNOWN = "（服务端未提供工具名）";

/** 解析一帧 `permission_pending`。只认字段本身，不做任何猜测性兜底。 */
export function parsePermissionPending(
  xy: Record<string, unknown>,
): PermissionFrame {
  const requestId = String(xy.request_id ?? "").trim();
  if (!requestId) {
    return {
      kind: "unresolvable",
      detail: "授权帧缺少 request_id：本次无法决议（未向服务端发送任何决定）",
    };
  }
  const tool = String(xy.tool_name ?? "").trim() || TOOL_UNKNOWN;
  const promptRaw = xy.prompt ?? xy.reason;
  return {
    kind: "open",
    prompt: {
      requestId,
      tool,
      prompt: promptRaw == null ? "" : String(promptRaw),
    },
  };
}
