import {expect, it} from 'vitest';
import type {ChatMessage} from '@/lib/types';
import {settleStoppedTools} from './stoppedTools';

it('settles only tools captured by the stop and retains a new running tool', () => {
	const old = {id: 'old', role: 'tool', text: '', createdAt: 1, toolStatus: 'waiting'} as ChatMessage;
	const current = {...old, id: 'new', toolStatus: 'running'} as ChatMessage;
	const result = settleStoppedTools([old, current], new Set(['old']));
	expect(result.changed).toBe(true); expect(result.messages[0]?.toolStatus).toBe('error');
	expect(result.messages[1]).toBe(current);
});

it('retains a late successful result of a stopped tool', () => {
	const row = {id: 'old', role: 'tool', text: 'success', createdAt: 1, toolStatus: 'done'} as ChatMessage;
	const result = settleStoppedTools([row], new Set(['old']));
	expect(result.changed).toBe(false); expect(result.messages[0]).toBe(row);
});
