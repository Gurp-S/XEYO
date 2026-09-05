import {describe, expect, it} from 'vitest';
import {groupTranscript, patchTranscriptTail} from './groupTranscript';
import type {ChatMessage} from './types';

const msg = (
	partial: Partial<ChatMessage> & Pick<ChatMessage, 'id' | 'role' | 'text'>,
): ChatMessage => ({
	createdAt: 1,
	...partial,
});

describe('groupTranscript', () => {
	it('pairs legacy call + result into one tool view', () => {
		const blocks = groupTranscript([
			msg({id: 'u', role: 'user', text: 'hi'}),
			msg({
				id: 'c',
				role: 'tool',
				toolName: 'echo',
				text: 'call {"text":"x"}',
			}),
			msg({
				id: 'r',
				role: 'tool',
				toolName: 'echo',
				text: 'x',
			}),
			msg({id: 'a', role: 'assistant', text: 'done'}),
		]);
		expect(blocks).toHaveLength(2);
		expect(blocks[0]?.kind).toBe('user');
		const turn = blocks[1];
		expect(turn?.kind).toBe('turn');
		if (turn?.kind !== 'turn') {
			return;
		}
		expect(turn.items).toHaveLength(2);
		expect(turn.items[0]).toMatchObject({
			kind: 'tool',
			tool: {name: 'echo', input: '{"text":"x"}', result: 'x', status: 'done'},
		});
		expect(turn.items[1]).toMatchObject({
			kind: 'assistant',
			message: {text: 'done'},
		});
	});

	it('keeps modern in-place tool rows as one item', () => {
		const blocks = groupTranscript([
			msg({id: 'u', role: 'user', text: 't'}),
			msg({
				id: 't1',
				role: 'tool',
				toolName: 'getTime',
				toolInput: '{}',
				toolStatus: 'done',
				text: '2026-08-08',
			}),
		]);
		const turn = blocks[1];
		expect(turn?.kind).toBe('turn');
		if (turn?.kind !== 'turn') {
			return;
		}
		expect(turn.items).toHaveLength(1);
		expect(turn.items[0]).toMatchObject({
			kind: 'tool',
			tool: {id: 't1', status: 'done', result: '2026-08-08'},
		});
	});

	it('attaches streaming to the active turn', () => {
		const blocks = groupTranscript(
			[msg({id: 'u', role: 'user', text: 'q'})],
			{streamingText: 'hello', isLoading: true},
		);
		expect(blocks).toHaveLength(2);
		expect(blocks[1]).toMatchObject({
			kind: 'turn',
			streaming: 'hello',
			active: true,
		});
	});

	it('treats tool with result body as settled even if status still running', () => {
		const blocks = groupTranscript([
			msg({id: 'u', role: 'user', text: 't'}),
			msg({
				id: 't1',
				role: 'tool',
				toolName: 'Read',
				toolInput: '{"file_path":"missing.txt"}',
				toolStatus: 'running',
				text: 'File does not exist',
			}),
		]);
		const turn = blocks[1];
		expect(turn?.kind).toBe('turn');
		if (turn?.kind !== 'turn') {
			return;
		}
		expect(turn.items[0]).toMatchObject({
			kind: 'tool',
			tool: {status: 'done', result: 'File does not exist'},
		});
	});

	it('settles orphan running tools on inactive history turns', () => {
		const blocks = groupTranscript([
			msg({id: 'u', role: 'user', text: 't'}),
			msg({
				id: 't1',
				role: 'tool',
				toolName: 'TodoWrite',
				toolInput: '{"todos":[]}',
				toolStatus: 'running',
				text: '',
			}),
		]);
		const turn = blocks[1];
		expect(turn?.kind).toBe('turn');
		if (turn?.kind !== 'turn') {
			return;
		}
		expect(turn.active).toBe(false);
		expect(turn.items[0]).toMatchObject({
			kind: 'tool',
			tool: {status: 'error'},
		});
	});

	it('settles orphan running on last turn once loading ends', () => {
		const messages = [
			msg({id: 'u', role: 'user', text: 't'}),
			msg({
				id: 't1',
				role: 'tool',
				toolName: 'TodoWrite',
				toolInput: '{"todos":[]}',
				toolStatus: 'running',
				text: '',
			}),
		];
		const live = groupTranscript(messages, {isLoading: true});
		const liveTurn = live[1];
		expect(liveTurn?.kind).toBe('turn');
		if (liveTurn?.kind === 'turn') {
			expect(liveTurn.active).toBe(true);
			expect(liveTurn.items[0]).toMatchObject({
				kind: 'tool',
				tool: {status: 'running'},
			});
		}

		const done = groupTranscript(messages, {isLoading: false});
		const doneTurn = done[1];
		expect(doneTurn?.kind).toBe('turn');
		if (doneTurn?.kind === 'turn') {
			expect(doneTurn.active).toBe(false);
			expect(doneTurn.items[0]).toMatchObject({
				kind: 'tool',
				tool: {status: 'error'},
			});
		}
	});

	it('keeps last turn active while loading even without stream text', () => {
		const blocks = groupTranscript(
			[
				msg({id: 'u', role: 'user', text: 'q'}),
				msg({
					id: 't1',
					role: 'tool',
					toolName: 'Write',
					toolInput: '{"file_path":"a.txt","content":"x"}',
					toolStatus: 'done',
					text: 'ok +1 -0',
				}),
			],
			{isLoading: true, statusText: ''},
		);
		const turn = blocks[1];
		expect(turn).toMatchObject({kind: 'turn', active: true});
	});

	it('patchTranscriptTail reuses history blocks when only stream text grows', () => {
		const messages = [
			msg({id: 'u', role: 'user', text: 'q'}),
			msg({id: 'a', role: 'assistant', text: 'hi'}),
		];
		const first = groupTranscript(messages, {streamingText: 'he'});
		const second = patchTranscriptTail(first, {streamingText: 'hello'});
		expect(second[0]).toBe(first[0]);
		expect(second[1]).not.toBe(first[1]);
		expect(second[1]).toMatchObject({
			kind: 'turn',
			streaming: 'hello',
			active: true,
		});
		expect(first[1]).toMatchObject({kind: 'turn', streaming: 'he'});
	});

	it('hides drain-precommitted assistant while streamingShown catches up', () => {
		const full = '### 多 Agent 运行结果\n\n- done';
		const blocks = groupTranscript(
			[
				msg({id: 'u', role: 'user', text: '跑批'}),
				msg({id: 'a', role: 'assistant', text: full}),
			],
			{streamingText: '### 多 Agent', isLoading: true},
		);
		const turn = blocks[1];
		expect(turn?.kind).toBe('turn');
		if (turn?.kind !== 'turn') {
			return;
		}
		expect(turn.streaming).toBe('### 多 Agent');
		expect(turn.items.some(i => i.kind === 'assistant')).toBe(false);
	});

	it('hides drain duplicate when streamingShown has trailing newline vs trimmed commit', () => {
		const blocks = groupTranscript(
			[
				msg({id: 'u', role: 'user', text: 'q'}),
				msg({id: 'a', role: 'assistant', text: 'hello'}),
			],
			{streamingText: 'hello\n', isLoading: true},
		);
		const turn = blocks[1];
		expect(turn?.kind).toBe('turn');
		if (turn?.kind !== 'turn') {
			return;
		}
		expect(turn.items.some(i => i.kind === 'assistant')).toBe(false);
		expect(turn.streaming).toBe('hello\n');
	});

	it('keeps prior assistant when turn ends with a tool (not drain)', () => {
		const blocks = groupTranscript(
			[
				msg({id: 'u', role: 'user', text: 'q'}),
				msg({id: 'a', role: 'assistant', text: 'OK I will look'}),
				msg({
					id: 't1',
					role: 'tool',
					toolName: 'Read',
					toolInput: '{}',
					toolStatus: 'running',
					text: '',
				}),
			],
			{streamingText: 'OK', isLoading: true},
		);
		const turn = blocks[1];
		expect(turn?.kind).toBe('turn');
		if (turn?.kind !== 'turn') {
			return;
		}
		expect(turn.items.some(i => i.kind === 'assistant')).toBe(true);
	});
});
