/** Whether a task card has an addressable agent transcript to open. */
export function canOpenAgentTask(agentId?: string): boolean {
	return Boolean(agentId?.trim());
}

/** Retrying starts new model work and is unavailable from archived sessions. */
export function canRetryAgentTask(archived: boolean, agentId?: string): boolean {
	return !archived && canOpenAgentTask(agentId);
}
