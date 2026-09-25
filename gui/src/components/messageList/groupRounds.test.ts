import {describe, expect, it} from 'vitest';
import type {MultiAgentTaskView} from '@/lib/api';
import type {ChatMessage} from '@/lib/types';
import {roundsWithAgentTasks} from './groupRounds';
import type {Round} from './types';

const round = (id: string, createdAt: number): Round => ({
	id,
	user: {id: `user-${id}`, role: 'user', text: id, createdAt} satisfies ChatMessage,
	rest: [],
	agentTasks: [],
});

const task = (uid: string, batchAt?: number): MultiAgentTaskView => ({
	uid,
	taskId: `task-${uid}`,
	agentId: `agent-${uid}`,
	desc: uid,
	status: 'done',
	...(batchAt != null ? {batchAt} : {}),
});

describe('roundsWithAgentTasks', () => {
	it('anchors tasks without a timestamp to the earliest round', () => {
		const rounds = [round('first', 100), round('second', 200)];
		const result = roundsWithAgentTasks(rounds, [task('legacy')]);

		expect(result[0]?.agentTasks.map(item => item.uid)).toEqual(['legacy']);
		expect(result[1]?.agentTasks).toEqual([]);
	});

	it('keeps timestamped tasks anchored to the latest preceding user round', () => {
		const rounds = [round('first', 100), round('second', 200)];
		const result = roundsWithAgentTasks(rounds, [task('current', 250)]);

		expect(result[0]?.agentTasks).toEqual([]);
		expect(result[1]?.agentTasks.map(item => item.uid)).toEqual(['current']);
	});
});
