import {describe, expect, it} from 'vitest';
import {
	buildOpsTrail,
	buildReplayScript,
	collectAgentPresence,
	digestConversationOps,
	latestHitForNode,
	toWorkspaceRel,
} from './agentPresence';
import type {ChatMessage} from './types';

function tool(
	name: string,
	input: Record<string, unknown>,
	status: ChatMessage['toolStatus'] = 'running',
): ChatMessage {
	return {
		id: `t-${name}-${JSON.stringify(input)}`,
		role: 'tool',
		text: '',
		toolName: name,
		toolInput: JSON.stringify(input),
		toolStatus: status,
		createdAt: 1,
	};
}

describe('toWorkspaceRel', () => {
	it('strips absolute workspace prefix', () => {
		expect(
			toWorkspaceRel('D:\\lea\\XenYon code\\gui\\src\\a.ts', 'D:\\lea\\XenYon code'),
		).toBe('gui/src/a.ts');
	});

	it('keeps already-relative paths', () => {
		expect(toWorkspaceRel('./python/engine/a.py', 'D:/proj')).toBe(
			'python/engine/a.py',
		);
	});

	it('reads notebook_path', () => {
		const hits = collectAgentPresence(
			[
				{id: 'u', role: 'user', text: 'x', createdAt: 0},
				{
					id: 't',
					role: 'tool',
					text: '',
					toolName: 'NotebookEdit',
					toolInput: JSON.stringify({notebook_path: 'n.ipynb'}),
					toolStatus: 'running',
					createdAt: 1,
				},
			],
			'',
		);
		expect(hits[0]?.relPath).toBe('n.ipynb');
	});
});

describe('collectAgentPresence', () => {
	it('extracts Read/Edit paths and flags the running one', () => {
		const messages: ChatMessage[] = [
			{id: 'u', role: 'user', text: 'go', createdAt: 0},
			{
				id: 'a',
				role: 'assistant',
				text: '',
				createdAt: 1,
			},
			tool('Read', {file_path: 'gui/src/stores/chatStore.ts'}, 'done'),
			tool('Edit', {file_path: 'D:/proj/gui/src/stores/chatStore.ts'}, 'running'),
		];
		const hits = collectAgentPresence(messages, 'D:/proj');
		expect(hits.map(h => h.relPath)).toEqual([
			'gui/src/stores/chatStore.ts',
			'gui/src/stores/chatStore.ts',
		]);
		expect(hits[1]?.running).toBe(true);
		expect(hits[1]?.verb).toBe('Editing');
	});

	it('matches package nodes by prefix', () => {
		const hits = collectAgentPresence(
			[
				{id: 'u', role: 'user', text: 'x', createdAt: 0},
				tool('Read', {path: 'python/engine/query_loop.py'}, 'running'),
			],
			'',
		);
		const latest = latestHitForNode(hits, 'python/engine', 'package');
		expect(latest?.running).toBe(true);
		expect(latestHitForNode(hits, 'python/tools', 'package')).toBeNull();
	});
});

describe('digestConversationOps', () => {
	it('dedupes paths and prefers running', () => {
		const hits = collectAgentPresence(
			[
				{id: 'u', role: 'user', text: 'go', createdAt: 0},
				tool('Read', {file_path: 'a.ts'}, 'done'),
				tool('Edit', {file_path: 'a.ts'}, 'running'),
				tool('Read', {file_path: 'b.ts'}, 'done'),
			],
			'',
		);
		const ops = digestConversationOps(hits);
		expect(ops.map(o => o.relPath)).toEqual(['a.ts', 'b.ts']);
		expect(ops[0]?.running).toBe(true);
		expect(ops[0]?.verb).toBe('Editing');
		expect(ops[0]?.count).toBe(2);
	});
});

describe('buildOpsTrail', () => {
	it('connects consecutive distinct paths in time order', () => {
		const hits = [
			{
				relPath: 'a.ts',
				verb: 'Reading',
				running: false,
				toolName: 'Read',
				createdAt: 1,
			},
			{
				relPath: 'a.ts',
				verb: 'Editing',
				running: false,
				toolName: 'Edit',
				createdAt: 2,
			},
			{
				relPath: 'b.ts',
				verb: 'Reading',
				running: true,
				toolName: 'Read',
				createdAt: 3,
			},
		];
		expect(buildOpsTrail(hits)).toEqual([{from: 'a.ts', to: 'b.ts'}]);
	});
});

describe('buildReplayScript', () => {
	it('keeps chronological frames without collapsing same path', () => {
		const hits = collectAgentPresence(
			[
				{id: 'u', role: 'user', text: 'go', createdAt: 0},
				tool('Read', {file_path: 'a.ts'}, 'done'),
				tool('Edit', {file_path: 'a.ts'}, 'done'),
				tool('Read', {file_path: 'b.ts'}, 'running'),
			],
			'',
		);
		const frames = buildReplayScript(hits);
		expect(frames.map(f => `${f.verb}:${f.relPath}`)).toEqual([
			'Read:a.ts',
			'Edited:a.ts',
			'Reading:b.ts',
		]);
		expect(frames).toHaveLength(3);
	});
});
