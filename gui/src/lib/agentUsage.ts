export function agentUsageTitle(task: {tokensUsed?: number; costCny?: number | null; costPartial?: boolean}): string {
	const tokens = `共消耗 ${(task.tokensUsed ?? 0).toLocaleString()} tokens`;
	if (task.costCny == null) return `${tokens}，费用未知`;
	return `${tokens}，${task.costPartial ? '已知费用' : '约'} ¥${task.costCny.toFixed(4)}${task.costPartial ? '（部分费用未知）' : ''}`;
}
