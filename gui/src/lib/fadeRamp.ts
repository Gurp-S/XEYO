/** 流式末尾渐变的共用 ramp：码点窗口与逐字透明度。 */

/** 本帧新增码点数 → 渐变窗口；快时窗口加长。 */
export function fadeWindowForStep(step: number): number {
	const s = Math.max(1, step);
	return Math.min(48, Math.max(16, 12 + s * 6));
}

/**
 * fromEnd=0 为最末一字（最淡）；fromEnd=window-1 接近实心。
 * t^1.5 缓入：窗口前半段快速离开实心区，渐变在中段就明显可见。
 */
export function fadeOpacityForOffset(fromEnd: number, window: number): number {
	const t = window <= 1 ? 1 : fromEnd / (window - 1);
	const eased = Math.min(1, Math.max(0, t)) ** 1.5;
	return 0.12 + 0.88 * eased;
}
