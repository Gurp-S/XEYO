/**
 * 按 session id 索引的内存 Todo 面板关闭记录。
 * 手动清除实时清单；较新的 TodoWrite（不同 snapshot id）
 * 会再次显示。永不持久化。
 */

const dismissedBySession = new Map<string, string>();

/** 隐藏此 TodoWrite 快照，直到较新的列表替换它。 */
export function dismissTodoSnapshot(
	sessionId: string,
	snapshotId: string,
): void {
	dismissedBySession.set(sessionId, snapshotId);
}

export function isTodoSnapshotDismissed(
	sessionId: string,
	snapshotId: string,
): boolean {
	return dismissedBySession.get(sessionId) === snapshotId;
}

export function clearTodoDismissal(sessionId: string): void {
	dismissedBySession.delete(sessionId);
}
