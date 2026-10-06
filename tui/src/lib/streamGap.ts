/**
 * streamGap.ts — 引擎告知"这条连接的投递缺了帧"之后，TUI 的收尾判定。
 *
 * 为什么单独成模块：TUI 的测试工装只有 `node --test`（没有渲染 App 的 ink 夹具），
 * 而这段逻辑的失败形态正是本项目反复踩的那族——**把缺段当完整内容留下**。
 * 判定放在可测的纯函数里，App.tsx 只负责接线。
 *
 * 上游契约见 `python/engine/turn_runner.py` 的 `_stream_gap_frame`：
 * 每连接额度溢出或环形缓冲挤帧时，服务端在 `[DONE]` 之前发一帧
 * `xy.type = "stream_gap"` 并带 `dropped_through_event_id`。引擎侧正文是完整落盘的，
 * 丢的只是这一次投递 ⇒ 客户端必须回拉 transcript 对账，拉不到就必须出声。
 */
import type { TimelineItem } from "../types.js";

/** 帧是不是"缺帧通知"；是则返回缺到哪个事件（>0），否则返回 0。 */
export function gapThroughOf(xy: Record<string, unknown>): number {
  if (String(xy.type ?? "") !== "stream_gap") return 0;
  const n = Number(xy.dropped_through_event_id ?? 0);
  // 帧到了但号丢了：仍按"缺过"处理，绝不能退化成"没缺"。
  return Number.isFinite(n) && n > 0 ? n : 1;
}

/** transcript 里**最后一条** assistant 正文（没有则 null）。取第一条＝拿旧轮冒充当前轮。 */
export function lastAssistantText(items: TimelineItem[]): string | null {
  let text: string | null = null;
  for (const item of items) {
    if (item.kind === "assistant") text = item.text;
  }
  return text;
}

/** 服务端 transcript 行的最小形状（`api/sse.ts` 的 LoadedMessage 是它的超集）。 */
export type LoadedRow = { role?: string; text?: string; isThought?: boolean };

/** 直接按服务端行取最后一条 assistant 正文：`isThought` 是投影出的思考行，不是正文。 */
export function lastAssistantTextFromRows(
  rows: readonly LoadedRow[],
): string | null {
  let text: string | null = null;
  for (const row of rows) {
    if (row.role === "assistant" && !row.isThought) text = row.text ?? "";
  }
  return text;
}

export type GapOutcome = "recovered" | "absent" | "failed";

/** 收尾文案：三种结局都必须点名"缺了帧"，只有真补齐了才说"已补齐"。 */
export function gapNote(
  gapThrough: number,
  outcome: GapOutcome,
  detail = "",
): string {
  const head = `本条回答在传输中缺了帧（到事件 ${gapThrough}）`;
  if (outcome === "recovered") return `${head}，正文已按服务端记录补齐`;
  if (outcome === "absent")
    return `⚠ ${head}，服务端记录里也没找到这条正文 —— 内容可能不完整，可用 /retry 重发`;
  return `⚠ ${head}，补齐失败${detail ? `：${detail}` : ""} —— 内容可能不完整，可用 /retry 重发`;
}

/**
 * 回拉服务端正文并给出补齐结果。
 * `loadText` 由调用方注入（App 走时间线映射、无头 JSON 走服务端行），
 * 这样这条判据能脱离网络与渲染层被逐臂校。
 */
export async function recoverAssistantAfterGap(deps: {
  gapThrough: number;
  loadText: () => Promise<string | null>;
}): Promise<{ text: string | null; note: string }> {
  try {
    const text = await deps.loadText();
    if (text == null) {
      return { text: null, note: gapNote(deps.gapThrough, "absent") };
    }
    return { text, note: gapNote(deps.gapThrough, "recovered") };
  } catch (e) {
    return {
      text: null,
      note: gapNote(
        deps.gapThrough,
        "failed",
        e instanceof Error ? e.message : String(e),
      ),
    };
  }
}
