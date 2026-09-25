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

	it('keeps the active workflow when the latest user message is queued', () => {
		const messages: ChatMessage[] = [
			{id: 'u1', role: 'user', text: 'inspect the file', createdAt: 1},
			tool('Read', {file_path: 'src/a.ts'}, 'running', 'read-1'),
			{
				id: 'u2',
				role: 'user',
				text: 'also check this',
				queueState: 'queued',
				createdAt: 2,
			},
		];

		const steps = buildTurnWorkflow(messages);
		expect(steps.map(step => step.id)).toEqual(['read-1']);
		expect(steps[0]?.running).toBe(true);
	});

	it('starts a fresh workflow after a queued message begins delivery', () => {
		const queued: ChatMessage = {
			id: 'u2',
			role: 'user',
			text: 'now process this',
			queueState: 'delivering',
			createdAt: 2,
		};
		const messages: ChatMessage[] = [
			{id: 'u1', role: 'user', text: 'previous task', createdAt: 1},
			tool('Read', {file_path: 'src/previous.ts'}, 'done', 'read-previous'),
			queued,
			tool('Edit', {file_path: 'src/current.ts'}, 'running', 'edit-current'),
		];

		expect(buildTurnWorkflow(messages).map(step => step.id)).toEqual([
			'edit-current',
		]);
	});
});
