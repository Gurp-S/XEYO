/** 将窗口值向下取整为正整数；空值、非有限数和不足一个 token 的值无效。 */
export function normalizeWindowLimit(value: unknown): number | undefined {
	if (typeof value !== 'number' || !Number.isFinite(value)) {
		return undefined;
	}
	const limit = Math.floor(value);
	return limit > 0 ? limit : undefined;
}
