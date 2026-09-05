export type AgentMode = 'agent' | 'plan' | 'ask';

export function normalizeAgentMode(value: unknown): AgentMode {
	return value === 'plan' || value === 'ask' ? value : 'agent';
}
