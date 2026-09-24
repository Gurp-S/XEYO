function safeAttempt(attempt: number): number {
	return Number.isFinite(attempt) ? Math.max(1, Math.floor(attempt)) : 1;
}

/** Compact user-facing status for the provider retry phase of a turn. */
export function formatLlmRetryWaiting(
	attempt: number,
	nextRetryMs: number,
): string {
	const retryInSeconds = Number.isFinite(nextRetryMs)
		? Math.max(0, Math.ceil(nextRetryMs / 1000))
		: 0;
	const retry = safeAttempt(attempt);
	return retryInSeconds > 0
		? `模型请求暂时失败，${retryInSeconds} 秒后重试（第 ${retry} 次）`
		: `模型请求暂时失败，正在第 ${retry} 次重试`;
}

export function formatLlmRetryStarted(attempt: number): string {
	return `正在重试模型请求（第 ${safeAttempt(attempt)} 次）`;
}
