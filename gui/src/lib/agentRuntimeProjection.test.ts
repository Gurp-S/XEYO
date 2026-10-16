import {describe, expect, it} from 'vitest';
import {projectManagedAgents, beginAgentListRead, agentListReadCurrent, invalidateAgentListRead} from './agentRuntimeProjection';
import type {MultiAgentTaskView, SessionAgentMeta} from '@/lib/api';

const running: MultiAgentTaskView = {uid: 'u', taskId: 't', agentId: 'a', desc: 'd', status: 'running', attemptId: '1', batchAt: 10, inboxCount: 1};
const done: SessionAgentMeta = {agentId: 'a', taskId: 't', desc: 'd', status: 'done', resultPreview: 'result', hasTranscript: true, startedAt: 10, updatedAt: 20, attemptId: '1', inboxCount: 0};
describe('durable background agent cards', () => {
	it('rejects stale reads across overlapping fetches and fresh SSE attempts', () => {
		const owner = {}, other = {};
		const first = beginAgentListRead(owner, 's');
		const second = beginAgentListRead(owner, 's');
		beginAgentListRead(other, 's');
		expect(agentListReadCurrent(owner, 's', first)).toBe(false);
		expect(agentListReadCurrent(owner, 's', second)).toBe(true);
		invalidateAgentListRead(owner, 's');
		expect(agentListReadCurrent(owner, 's', second)).toBe(false);
	});
	it('settles an existing card and clears the delivered mailbox count', () => {
		const [task] = projectManagedAgents([running], [done]);
		expect(task).toMatchObject({uid: 'u', status: 'done', result: 'result', inboxCount: 0});
	});
	it('replaces an attempt and rejects an older API response', () => {
		const tasks = projectManagedAgents([running], [{...done, attemptId: '2', startedAt: 30, updatedAt: 30, status: 'running'}]);
		expect(tasks).toHaveLength(1);
		expect(tasks[0]).toMatchObject({attemptId: '2', status: 'running', batchAt: 30});
		expect(projectManagedAgents(tasks, [done])).toEqual(tasks);
	});
	it('leaves legacy SSE state intact', () => {
		expect(projectManagedAgents([running], [{...done, attemptId: undefined}])).toEqual([running]);
	});
});
