const TOKEN_UNITS = ['', 'k', 'M', 'B', 'T'] as const;

/** 将 Token 以紧凑且稳定的单位显示，原始值仍由后端保留。 */
export function formatTokenCount(tokens: number): string {
	const value = Math.max(0, Math.round(Number.isFinite(tokens) ? tokens : 0));
	let unitIndex = 0;
	let scaled = value;
	while (scaled >= 1000 && unitIndex < TOKEN_UNITS.length - 1) {
		scaled /= 1000;
		unitIndex += 1;
	}
	if (unitIndex === 0) {
		return `${scaled.toLocaleString('en-US')} tok`;
	}
	const rounded = Number(scaled.toFixed(2));
	if (rounded >= 1000 && unitIndex < TOKEN_UNITS.length - 1) {
		return `${(rounded / 1000).toFixed(2)}${TOKEN_UNITS[unitIndex + 1]} tok`;
	}
	return `${rounded.toFixed(2)}${TOKEN_UNITS[unitIndex]} tok`;
}

export function formatCnyAmount(cny: number | null | undefined): string {
	if (cny == null || !Number.isFinite(cny)) {
		return '费用待确认';
	}
	return `¥${Math.max(0, cny).toFixed(2)}`;
}

/** 顶栏用量芯片：累计消耗 / 输出token · 模型窗口占用%（最近一枪 context_tokens / 窗口，未知则省略）。 */
export function formatUsageChipPreview(
	consumedTokens: number | null | undefined,
	outputTokens: number | null | undefined,
	contextPercent?: string | null,
): string {
	const left =
		consumedTokens != null && Number.isFinite(consumedTokens)
			? formatTokenCount(consumedTokens)
			: '—';
	const hasOut =
		outputTokens != null && Number.isFinite(outputTokens);
	const mid = hasOut ? formatTokenCount(outputTokens) : null;
	const pct = contextPercent == null ? '占用待确认' : `${contextPercent}%`;
	return mid ? `${left} / ${mid} · ${pct}` : `${left} · ${pct}`;
}

/**
 * 缓存命中率显示（显示精度收敛为一位小数）：「计费输入 = 命中 + 未命中(含写档)」。
 *
 * - 常规：一位小数（例 85.2）
 * - 一位小数已四舍五入到 100（但并非全命中）→ 不谎报 100，按真实分位给高精度 99.9x
 * - 全命中 → 100；无计费输入 → null（显示"暂无数据"）
 *
 * - hit：会话累计命中（cacheHitTokens，DeepSeek = prompt_cache_hit_tokens）
 * - miss：会话累计未命中（cacheMissTokens；DeepSeek 无独立 write 档，
 *   未命中已含写入部分 → 按 uncached+write 口径计入）
 */
export function formatCacheHitPercent(
	hit: number,
	miss: number,
): string | null {
	const read = Math.max(0, Number.isFinite(hit) ? hit : 0);
	const writeAndUncached = Math.max(0, Number.isFinite(miss) ? miss : 0);
	const denominator = read + writeAndUncached;
	if (denominator === 0) return null;
	if (writeAndUncached === 0) return '100';
	const oneDecimal = (read / denominator * 100).toFixed(1);
	if (oneDecimal !== '100.0') return oneDecimal;
	// 一位小数已撞 100% 但并非全命中：取高精度分位（99.9x），不谎报 100。
	return nearHundredPrecision(writeAndUncached, denominator);
}

/** 99.9x 高精度分位：一位小数进位到 100 时按真实分位补足小数位。 */
function nearHundredPrecision(missedTokens: number, denominator: number): string {
	let decimalPlaces = 1;
	let scaledDoubleGap = missedTokens * 200;
	const denominatorTens = Math.floor(denominator / 10);
	while (scaledDoubleGap <= denominatorTens) {
		scaledDoubleGap *= 10;
		decimalPlaces += 1;
	}
	const denominatorOnes = denominator % 10;
	let roundedLoss = 5;
	for (let loss = 1; loss < 5; loss += 1) {
		const factor = loss * 2 + 1;
		const threshold = factor * denominatorTens + Math.floor((factor * denominatorOnes) / 10);
		if (scaledDoubleGap <= threshold) {
			roundedLoss = loss;
			break;
		}
	}
	return `99.${'9'.repeat(decimalPlaces - 1)}${10 - roundedLoss}`;
}
