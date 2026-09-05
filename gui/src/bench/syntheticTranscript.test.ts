import {describe, expect, it} from 'vitest';
import {
	buildSyntheticMessages,
	buildSyntheticStreamReply,
} from './syntheticTranscript';
import {groupTranscript, patchTranscriptTail} from '@/lib/groupTranscript';

describe('syntheticTranscript', () => {
	it('同一 seed 产出逐字节相同的转录', () => {
		const a = JSON.stringify(buildSyntheticMessages({rounds: 40, seed: 7}));
		const b = JSON.stringify(buildSyntheticMessages({rounds: 40, seed: 7}));
		expect(a).toBe(b);
	});

	it('不同 seed 产出不同转录', () => {
		const a = JSON.stringify(buildSyntheticMessages({rounds: 20, seed: 1}));
		const b = JSON.stringify(buildSyntheticMessages({rounds: 20, seed: 2}));
		expect(a).not.toBe(b);
	});

	it('消息 id 唯一、文本非空、每轮以 user 开头且必有 assistant 回复', () => {
		const messages = buildSyntheticMessages({rounds: 120, seed: 3});
		const ids = new Set<string>();
		let seenAssistantSinceUser = false;
		let first = true;
		for (const m of messages) {
			expect(ids.has(m.id)).toBe(false);
			ids.add(m.id);
			expect(m.text.length).toBeGreaterThan(0);
			if (m.role === 'user') {
				if (!first) {
					// 两条相邻 user 之间必须存在 assistant 回复（轮的完整性）。
					expect(seenAssistantSinceUser).toBe(true);
				}
				first = false;
				seenAssistantSinceUser = false;
			} else if (m.role === 'assistant') {
				seenAssistantSinceUser = true;
			}
		}
		expect(first).toBe(false);
		expect(seenAssistantSinceUser).toBe(true);
		// 120 轮 → 每轮至少 2 条消息，tool 轮更多。
		expect(messages.length).toBeGreaterThanOrEqual(240);
	});

	it('tool 行是现代合并形态（toolInput + toolStatus=done + 结果体）', () => {
		const messages = buildSyntheticMessages({rounds: 200, seed: 5});
		const tools = messages.filter(m => m.role === 'tool');
		expect(tools.length).toBeGreaterThan(0);
		for (const t of tools) {
			expect(t.toolInput).toBeDefined();
			expect(t.toolStatus).toBe('done');
			expect(t.text.startsWith('call ')).toBe(false);
			expect(t.toolName).toBeTruthy();
		}
	});

	it('输出可直接走 groupTranscript / patchTranscriptTail 管线', () => {
		const messages = buildSyntheticMessages({rounds: 60, seed: 9});
		const blocks = groupTranscript(messages, {
			isLoading: false,
			streamingText: undefined,
		});
		// 每轮至少一个 user 块 → 块数 > 轮数。
		expect(blocks.length).toBeGreaterThan(60);
		const patched = patchTranscriptTail(blocks, {
			isLoading: true,
			streamingText: buildSyntheticStreamReply(11),
		});
		expect(patched.length).toBeGreaterThan(0);
		const last = patched[patched.length - 1]!;
		expect(last.kind === 'turn' && last.streaming).toBeTruthy();
	});
});
