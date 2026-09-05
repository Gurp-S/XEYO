import {describe, expect, it} from 'vitest';
import {
	countAgentActivitySteps,
	planAgentCardMounts,
} from './agentCardLayout';

describe('planAgentCardMounts', () => {
	it('concurrent: all cards after last contiguous Delegating', () => {
		const steps = [
			{verb: 'Thought'},
			{verb: 'Delegating', agent: true},
			{verb: 'Delegating', agent: true},
			{verb: 'Delegating', agent: true},
		];
		expect(planAgentCardMounts(steps, 3)).toEqual([
			{afterStepIndex: 3, taskStart: 0, taskEnd: 3},
		]);
	});

	it('serial: card after each Agent when Thought interrupts', () => {
		const steps = [
			{verb: 'Delegated', agent: true},
			{verb: 'Thought'},
			{verb: 'Failed', agent: true},
		];
		expect(planAgentCardMounts(steps, 2)).toEqual([
			{afterStepIndex: 0, taskStart: 0, taskEnd: 1},
			{afterStepIndex: 2, taskStart: 1, taskEnd: 2},
		]);
	});

	it('serial: does not dump pending tasks onto first Delegating', () => {
		const steps = [{verb: 'Delegated', agent: true}];
		// 店里已有 2 张卡，但步骤只有 1 条 → 只挂第 1 张
		expect(planAgentCardMounts(steps, 2)).toEqual([
			{afterStepIndex: 0, taskStart: 0, taskEnd: 1},
		]);
	});

	it('serial across tools: Read breaks the run', () => {
		const steps = [
			{verb: 'Delegating', agent: true},
			{verb: 'Read'},
			{verb: 'Delegating', agent: true},
		];
		expect(planAgentCardMounts(steps, 2)).toEqual([
			{afterStepIndex: 0, taskStart: 0, taskEnd: 1},
			{afterStepIndex: 2, taskStart: 1, taskEnd: 2},
		]);
	});

	it('countAgentActivitySteps includes Failed agents', () => {
		expect(
			countAgentActivitySteps([
				{verb: 'Delegated', agent: true},
				{verb: 'Failed', agent: true},
				{verb: 'Failed'},
			]),
		).toBe(2);
	});
});
