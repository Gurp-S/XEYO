/**
 * presence 退出延迟 —— 从实际 CSS 令牌读取，而不是在 TS 里另写一份数字。
 *
 * 为什么这么做：
 * `usePresence(open, exitMs)` 的退出延迟必须 **不小于** 对应容器的 CSS 退出过渡时长，
 * 否则子树会在过渡播完前被卸载，动画末帧被硬截断（面板越高越明显）。
 * 两侧各写各的数字已实测漂移出两处缺陷：
 *   - DockPresence：exitMs 180ms < `.xy-dock-presence` grid-template-rows 200ms
 *   - SettingsModal：exitMs 160ms < `.xy-modal-panel` transition 200ms
 *
 * 改为运行时读 `--duration-*` 自定义属性后，改 tokens.css 即自动生效，
 * 结构上不可能再漂移。该令牌与主题无关（不随 data-theme/data-scheme 变化），
 * 因此调用方只需按挂载 memo 一次。
 */

/** CSS 尚未就绪（jsdom 测试 / 样式表未应用）时的兜底；与 tokens.css 现值一致。 */
export const FALLBACK_DURATION_MS = {fast: 140, base: 200} as const;

export type DurationToken = keyof typeof FALLBACK_DURATION_MS;

/** presence 退出延迟余量：抵消定时器与合成帧的竞态，避免末帧仍被截断。 */
export const PRESENCE_EXIT_MARGIN_MS = 20;

/**
 * 读 `--duration-<token>`。
 * 解析不出合法毫秒值时回落 `FALLBACK_DURATION_MS`（而不是抛错——动效不该让界面挂掉）。
 */
export function cssDurationMs(token: DurationToken): number {
	const fallback = FALLBACK_DURATION_MS[token];
	if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') {
		return fallback;
	}
	const raw = getComputedStyle(document.documentElement)
		.getPropertyValue(`--duration-${token}`)
		.trim();
	const m = /^(\d+(?:\.\d+)?)ms$/.exec(raw);
	return m ? Number(m[1]) : fallback;
}

/** 按容器过渡时长推导 presence 退出延迟。 */
export function presenceExitMs(containerMs: number): number {
	return containerMs + PRESENCE_EXIT_MARGIN_MS;
}
