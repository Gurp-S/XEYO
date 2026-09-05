/**
 * roundVirtual.ts — 自研窗口化虚拟列表的纯几何层。
 *
 * 布局契约：VirtualRoundList 用 spacer 段补齐未挂载轮次，spacer 高度 =
 * Σ roundHeights 缓存高度（从未测过用 DEFAULT_ROUND_HEIGHT）。挂载轮次的
 * ResizeObserver 实测回写同一张表，因此前缀和与真实 DOM 布局一致
 * （RO 校正按帧合并，最多滞后一帧）。
 *
 * 不引入 TanStack Virtual：其 ResizeObserver → resizeItem → React state
 * 反馈环曾与 sticky / TurnRail 打架（React max update depth）。这里高度
 * 写入不落 React state，只有窗口边界真正变化时才触发一次渲染。
 */
import {getRoundHeightOrDefault} from './roundHeights';

/** 视口外上下各预留的像素（≈5-7 个轮次），让挂载/卸载的高度校正发生在视口外。 */
export const ROUND_WINDOW_OVERSCAN_PX = 900;

/** scrollElement 尚未可测量（首帧）时的兜底视口高度。 */
export const FALLBACK_VIEWPORT_H = 720;

export type RoundWindow = {
	/** 半开区间 [start, end)。 */
	start: number;
	end: number;
};

/** roundIds → 前缀和：prefix[i] = 轮次 i 的 content 坐标顶部偏移。长度 = count + 1。 */
export function computeRoundPrefix(roundIds: readonly string[]): number[] {
	const prefix = new Array<number>(roundIds.length + 1);
	prefix[0] = 0;
	let acc = 0;
	for (let i = 0; i < roundIds.length; i += 1) {
		acc += getRoundHeightOrDefault(roundIds[i]!);
		prefix[i + 1] = acc;
	}
	return prefix;
}

/**
 * content 坐标 offset（0 = 首轮顶部）→ 覆盖它的轮次下标。
 * 二分查找：prefix 单调递增；offset 越过末尾时返回 count。
 */
export function roundIndexAtOffset(prefix: number[], offset: number): number {
	const count = prefix.length - 1;
	if (count <= 0) {
		return 0;
	}
	let low = 0;
	let high = count;
	while (low < high) {
		const mid = (low + high + 1) >> 1;
		if (prefix[mid]! <= offset) {
			low = mid;
		} else {
			high = mid - 1;
		}
	}
	return Math.min(low, count);
}

/** scrollTop + 视口高 → 需要挂载的轮次窗口（含 overscan）。 */
export function roundWindowFor(
	prefix: number[],
	scrollTop: number,
	viewportH: number,
	overscanPx: number = ROUND_WINDOW_OVERSCAN_PX,
): RoundWindow {
	const count = prefix.length - 1;
	if (count <= 0) {
		return {start: 0, end: 0};
	}
	const viewH = Math.max(1, viewportH || FALLBACK_VIEWPORT_H);
	const top = Math.max(0, scrollTop - overscanPx);
	const bottom = scrollTop + viewH + overscanPx;
	const start = roundIndexAtOffset(prefix, top);
	const end = Math.min(count, roundIndexAtOffset(prefix, bottom) + 1);
	return {start, end};
}

/**
 * 视口锚点：当前压在内容顶边的那一轮 + 用户落在该轮内的像素占比。
 * 高度实测回写使前缀和整体平移时,用它把 scrollTop 重对齐回同一内容点。
 *
 * 当 scrollTop 已越过「估算内容末尾」(index 越界)返回 null —— 此时锚点无意义,
 * 强行补偿会把滚到底部的用户拽飞(见 VirtualRoundList.measure)。
 */
export function captureViewportAnchor(
	prefix: number[],
	scrollTop: number,
): {index: number; frac: number} | null {
	const count = prefix.length - 1;
	if (count <= 0) {
		return null;
	}
	const index = roundIndexAtOffset(prefix, scrollTop);
	if (index >= count) {
		return null;
	}
	const start = prefix[index] ?? 0;
	const h = (prefix[index + 1] ?? start) - start;
	const frac = h > 0 ? Math.min(1, Math.max(0, (scrollTop - start) / h)) : 0;
	return {index, frac};
}

/**
 * 用「重建后的前缀和 + 锚点」反解出应写入的 scrollTop。
 * 前缀和未变时恒等于原 scrollTop(恒等,零副作用);
 * 上方轮次长高 Δ 时,该值 = scrollTop + Δ,让视口内容原地不动。
 */
export function anchorScrollTop(
	prefix: number[],
	anchor: {index: number; frac: number},
): number {
	const start = prefix[anchor.index] ?? 0;
	const h = (prefix[anchor.index + 1] ?? start) - start;
	return start + anchor.frac * h;
}

/** 合并重叠/相邻区间，输出按 start 升序的不相交段。 */
export function mergeIntervals(list: RoundWindow[]): RoundWindow[] {
	if (list.length === 0) {
		return [];
	}
	const sorted = [...list].sort((a, b) => a.start - b.start || a.end - b.end);
	const out: RoundWindow[] = [{...sorted[0]!}];
	for (let i = 1; i < sorted.length; i += 1) {
		const last = out[out.length - 1]!;
		const cur = sorted[i]!;
		if (cur.start <= last.end) {
			last.end = Math.max(last.end, cur.end);
		} else {
			out.push({...cur});
		}
	}
	return out;
}
