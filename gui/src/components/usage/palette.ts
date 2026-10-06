/**
 * 分模型系列色：六档墨阶（`--xy-series-1..6`），第 7 个模型起循环。
 *
 * 只发 CSS 变量引用，不发字面色值——用量页的"不许出现写死色"门扫这一族文件。
 * 超过 6 个模型的日子靠环形卡底下的明细行区分，不靠颜色（同色系第 7 档已经分不出来）。
 */
export const SERIES_COUNT = 6;

export function seriesColor(index: number): string {
	const slot = (Math.max(0, Math.trunc(index)) % SERIES_COUNT) + 1;
	return `var(--xy-series-${slot})`;
}
