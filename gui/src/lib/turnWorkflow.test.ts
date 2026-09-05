import {describe, expect, it} from 'vitest';
import {buildTurnWorkflow, turnWorkflowToLanes} from './turnWorkflow';
import type {ChatMessage} from './types';

function tool(
	name: string,
	input: Record<string, unknown>,
	status: ChatMessage['toolStatus'] = 'running',
	id?: string,
): ChatMessage {
	return {
		id: id ?? `t-${name}`,
		role: 'tool',
		text: '',
		toolName: name,
		toolInput: JSON.stringify(input),
		toolStatus: status,
		createdAt: 1,
	};
}

describe('buildTurnWorkflow', () => {
	it('lanes the latest turn tools', () => {
		const messages: ChatMessage[] = [
			{id: 'u', role: 'user', text: 'go', createdAt: 0},
			{id: 'a', role: 'assistant', text: '', createdAt: 1},
			tool('Read', {file_path: 'gui/src/a.ts'}, 'done', 'r1'),
			tool('Edit', {file_path: 'gui/src/a.ts'}, 'running', 'e1'),
		];
		const steps = buildTurnWorkflow(messages);
		expect(steps.map(s => s.lane)).toEqual(['read', 'write']);
		expect(steps[1]?.running).toBe(true);
		const {edges, items} = turnWorkflowToLanes(steps, [
			'gui/src/a.ts',
			'gui/src/b.ts',
		]);
		expect(items.filter(i => i.layer === 'files')).toHaveLength(2);
		expect(items).toHaveLength(4);
		expect(edges).toContainEqual({from: 'r1', to: 'e1'});
		expect(edges).toContainEqual({from: 'gui/src/a.ts', to: 'gui/src/b.ts'});
	});
});
