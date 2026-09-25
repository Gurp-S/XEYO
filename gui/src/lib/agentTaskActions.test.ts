import {describe, expect, it} from 'vitest';
import {canOpenAgentTask, canRetryAgentTask} from './agentTaskActions';

describe('agent task actions', () => {
	it('does not expose a dead open action before an agent id arrives', () => {
		expect(canOpenAgentTask(undefined)).toBe(false);
		expect(canOpenAgentTask('  ')).toBe(false);
		expect(canOpenAgentTask('agent-1')).toBe(true);
	});

	it('prevents failed agent retries in archived sessions', () => {
		expect(canRetryAgentTask(true, 'agent-1')).toBe(false);
		expect(canRetryAgentTask(false, 'agent-1')).toBe(true);
		expect(canRetryAgentTask(false, undefined)).toBe(false);
	});
});
