import {describe, expect, it} from 'vitest';
import type {TurnItem} from '@/lib/groupTranscript';
import {proseFingerprint, toolsFingerprint} from './AssistantTurn';

const tool = (
	id: string,
	status: 'running' | 'done' | 'error',
	result = '',
): TurnItem => ({
	kind: 'tool',
	tool: {
		id,
		name: 'Read',
		input: '{"file_path":"a.ts"}',
		result,
		status,
		createdAt: 1,
	},
});

describe('AssistantTurn fingerprints', () => {
	it('stays stable across identical tool shapes (streaming ticks)', () => {
		const a: TurnItem[] = [
			{
				kind: 'assistant',
				message: {
					id: 'a1',
					role: 'assistant',
					text: 'hi',
					createdAt: 1,
				},
			},
			tool('t1', 'done', 'ok'),
		];
		const b = a.map(item =>
			item.kind === 'tool'
				? {
						kind: 'tool' as const,
						tool: {...item.tool},
					}
				: {
						kind: 'assistant' as const,
						message: {...item.message},
					},
		);
		expect(toolsFingerprint(a)).toBe(toolsFingerprint(b));
		expect(proseFingerprint(a)).toBe(proseFingerprint(b));
	});

	it('changes when a tool finishes', () => {
		const running = [tool('t1', 'running')];
		const done = [tool('t1', 'done', 'hello world')];
		expect(toolsFingerprint(running)).not.toBe(toolsFingerprint(done));
	});
});
