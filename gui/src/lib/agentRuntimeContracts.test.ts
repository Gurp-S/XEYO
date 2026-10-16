import {afterEach, expect, it, vi} from 'vitest';
import {interruptChat} from './api';
import {rememberTurnCursor} from './api/turnCursor';
import {agentUsageTitle} from './agentUsage';
import {parseSseBlock} from './api/core';

afterEach(() => {vi.unstubAllGlobals(); sessionStorage.clear();});

it('captures the observed turn before the interrupt request is delayed', async () => {
	rememberTurnCursor('s', 1, 'A');
	let body: Record<string, string> = {};
	let finish!: (value: Response) => void;
	vi.stubGlobal('fetch', vi.fn((_url, options) => {
		body = JSON.parse(options.body);
		return new Promise<Response>(resolve => {finish = resolve;});
	}));
	const request = interruptChat('s');
	rememberTurnCursor('s', 1, 'B');
	expect(body.expected_turn_id).toBe('A');
	finish(new Response(JSON.stringify({detail: 'turn_mismatch'}), {status: 409}));
	expect((await request).ok).toBe(false);
});

it('preserves unknown and partial child costs for display', () => {
	const event = parseSseBlock('data: {"xy":{"type":"multi_agent_progress","cost_cny":1.25,"cost_partial":true,"tokens_used":1234}}');
	expect(event).toMatchObject({costCny: 1.25, costPartial: true, tokensUsed: 1234});
	expect(agentUsageTitle({tokensUsed: 1234, costCny: 1.25, costPartial: true})).toContain('部分费用未知');
	expect(agentUsageTitle({tokensUsed: 1234, costCny: null})).toContain('费用未知');
	expect(agentUsageTitle({tokensUsed: 1234, costCny: 0})).toContain('¥0.0000');
});
