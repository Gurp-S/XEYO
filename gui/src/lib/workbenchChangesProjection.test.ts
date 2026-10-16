import {describe, expect, it, vi} from 'vitest';
import {writeFileSync, mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {groupTranscript, latestUserTurnBoundary} from './groupTranscript';
import {collectChangedFilesFromItems} from './toolActivity';
import * as activity from './toolActivity';
import type {ChatMessage} from './types';
import {createWorkbenchChangesProjection} from './workbenchChangesProjection';

function baseline(messages: ChatMessage[], messageId?: string) {
	const boundary = latestUserTurnBoundary(messages);
	const chosen = messageId ? messages.findIndex(m => m.id === messageId && m.role === 'user') : -1;
	const start = chosen >= 0 ? chosen : boundary?.index ?? 0;
	const next = messages.findIndex((m, i) => i > start && m.role === 'user' && !m.queueState && !m.localUndelivered && !m.uiOnly);
	return collectChangedFilesFromItems(groupTranscript(messages.slice(start, next < 0 ? undefined : next)).flatMap(b => b.kind === 'turn' ? b.items : []));
}
const user = (id: string): ChatMessage => ({id, role: 'user', text: id, createdAt: 1});
const tool = (id: string, patch: Partial<ChatMessage> = {}): ChatMessage => ({id, role: 'tool', toolName: 'Write',
	toolInput: JSON.stringify({file_path: 'src/A.ts', content: 'first\nsecond'}), toolStatus: 'done', text: 'created\n```diff\n+first\n+second\n```', createdAt: 2, ...patch});

describe('workbench projection agrees with the full transcript parser', () => {
	it('append, late result, error correction, removal, reorder and rollback', () => {
		const project = createWorkbenchChangesProjection();
		let messages = [user('u1'), tool('t1'), tool('t2', {toolStatus: 'running', text: ''})];
		const check = () => expect(project(messages)).toEqual(baseline(messages));
		check();
		messages = [...messages, {id: 'a', role: 'assistant', text: 'answer', createdAt: 3}]; check();
		messages = messages.map(m => m.id === 't2' ? {...m, text: 'updated +3 -1', toolStatus: 'done'} : m); check();
		messages = messages.map(m => m.id === 't1' ? {...m, text: '[error] failed', toolStatus: 'error'} : m); check();
		messages = [messages[0], messages[2], messages[1]]; check();
		messages = messages.slice(0, 2); check();
		messages = []; check();
	});
	it('legacy pairs, queue states, history selection and replacement sessions', () => {
		const project = createWorkbenchChangesProjection();
		const call = tool('call', {toolInput: undefined, toolStatus: undefined, text: 'call {"file_path":"old.ts","content":"x"}', toolUseId: 'id'});
		let messages = [user('old'), call, {...user('queued'), queueState: 'queued' as const}, tool('result', {toolInput: undefined, toolStatus: undefined, toolUseId: 'id', text: 'created +1 -0'})];
		for (const selected of [undefined, 'old', 'missing']) expect(project(messages, selected)).toEqual(baseline(messages, selected));
		messages = [...messages, user('new'), tool('new-tool', {toolInput: '{"file_path":"new.ts","content":"y"}'})];
		for (const selected of [undefined, 'old', 'new']) expect(project(messages, selected)).toEqual(baseline(messages, selected));
		messages = messages.map(m => m.id === 'result' ? {...m, toolUseId: 'different'} : m);
		expect(project(messages, 'old')).toEqual(baseline(messages, 'old'));
		for (const queueState of ['queued', 'delivering', 'syncing', 'stuck'] as const) {
			const next = [...messages, {...user('pending'), queueState}];
			expect(project(next)).toEqual(baseline(next));
		}
		const replacement = [user('new'), tool('new-tool', {text: '[error] no', toolStatus: 'error'})];
		expect(project(replacement)).toEqual(baseline(replacement));
	});
	it('unchanged tools keep the output identity during prose and queue updates', () => {
		const project = createWorkbenchChangesProjection();
		const messages = [user('u'), tool('t')];
		const first = project(messages);
		expect(project([...messages, {id: 'a', role: 'assistant', text: 'new prose', createdAt: 3}])).toBe(first);
		expect(project([...messages, {...user('q'), queueState: 'queued'}])).toBe(first);
	});
	it.skipIf(!process.env.XEYO_PERF_REPORT)('A/B: 1000 tools and 100 late updates; every output matches', () => {
		const initial = [user('u'), ...Array.from({length: 1000}, (_, i) => tool(`t${i}`, {
			toolInput: JSON.stringify({file_path: `src/f${i % 50}.ts`, content: 'line\n'.repeat(300)}),
			text: `updated\n\`\`\`diff\n${'+line\n'.repeat(30)}\`\`\``,
		}))];
		const frames: ChatMessage[][] = [];
		let messages = initial;
		for (let i = 0; i < 100; i++) {
			messages = messages.map((m, index) => index === i + 1 ? {...m, text: `updated +${i} -1`} : m);
			frames.push(messages);
		}
		const before: number[] = [], after: number[] = [];
		for (let run = 0; run < 7; run++) {
			const project = createWorkbenchChangesProjection();
			project(initial);
			const measure = (fn: typeof baseline, values: number[]) => {
				const start = performance.now();
				const outputs = frames.map(frame => fn(frame));
				values.push(performance.now() - start);
				return outputs;
			};
			const slow = run % 2 ? null : measure(baseline, before);
			const fast = measure(project, after);
			expect(fast).toEqual(slow ?? measure(baseline, before));
		}
		// Count actual inputs separately so instrumentation does not affect timings.
		const spy = vi.spyOn(activity, 'collectChangedFilesFromItems');
		frames.forEach(frame => baseline(frame));
		const baselineToolParses = spy.mock.calls.reduce((n, [items]) => n + items.filter(item => item.kind === 'tool').length, 0);
		const project = createWorkbenchChangesProjection();
		project(initial); spy.mockClear();
		frames.forEach(frame => project(frame));
		const optimizedToolParsesAfterWarmup = spy.mock.calls.reduce((n, [items]) => n + items.length, 0);
		spy.mockRestore();
		expect(baselineToolParses).toBe(100000);
		expect(optimizedToolParsesAfterWarmup).toBe(100);
		const report = {tools: 1000, updates: 100, beforeMs: before, afterMs: after,
			baselineToolParses, optimizedToolParsesAfterWarmup};
		if (process.env.XEYO_PERF_REPORT) {
			mkdirSync(dirname(process.env.XEYO_PERF_REPORT), {recursive: true});
			writeFileSync(process.env.XEYO_PERF_REPORT, JSON.stringify(report, null, 2));
		}
	}, 60000);
});
