import {describe, expect, it} from 'vitest';
import {toApiMessages} from './toApiMessages';
import type {ChatMessage} from './types';

describe('toApiMessages', () => {
	it('skips isThought and tool rows', () => {
		const msgs: ChatMessage[] = [
			{id: 'u1', role: 'user', text: 'hi', createdAt: 1},
			{
				id: 'th1',
				role: 'assistant',
				text: 'thinking…',
				isThought: true,
				createdAt: 2,
			},
			{
				id: 't1',
				role: 'tool',
				toolName: 'Grep',
				toolInput: '{"pattern":"foo"}',
				text: 'ok',
				createdAt: 3,
			},
			{id: 'a1', role: 'assistant', text: 'done', createdAt: 4},
		];
		expect(toApiMessages(msgs)).toEqual([
			{role: 'user', content: 'hi', id: 'u1'},
			{role: 'assistant', content: 'done', id: 'a1'},
		]);
	});

	it('merges consecutive assistant prose between tools', () => {
		const msgs: ChatMessage[] = [
			{id: 'u1', role: 'user', text: 'task', createdAt: 1},
			{id: 'a1', role: 'assistant', text: 'step one', createdAt: 2},
			{
				id: 't1',
				role: 'tool',
				toolName: 'Read',
				toolInput: '{}',
				text: 'ok',
				createdAt: 3,
			},
			{id: 'a2', role: 'assistant', text: 'step two', createdAt: 4},
			{id: 'u2', role: 'user', text: 'continue', createdAt: 5},
		];
		expect(toApiMessages(msgs)).toEqual([
			{role: 'user', content: 'task', id: 'u1'},
			{role: 'assistant', content: 'step one\n\nstep two', id: 'a1'},
			{role: 'user', content: 'continue', id: 'u2'},
		]);
	});
});
