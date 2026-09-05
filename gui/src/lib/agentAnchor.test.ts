import {describe, expect, it} from 'vitest';
import {splitAtAgentAnchor, XEYO_AGENTS_ANCHOR} from './agentAnchor';

describe('splitAtAgentAnchor', () => {
	it('splits allocation and summary on xeyo anchor', () => {
		const text = `**分配说明**\n\n并行三个文件${XEYO_AGENTS_ANCHOR}已创建三个 md。`;
		const {before, after, anchored} = splitAtAgentAnchor(text);
		expect(anchored).toBe(true);
		expect(before).toContain('分配说明');
		expect(before).toContain('并行');
		expect(before).not.toContain('已创建');
		expect(after).toContain('已创建三个 md');
		expect(after).not.toContain('xeyo:agents');
	});

	it('scrubs leaked trailing bracket', () => {
		const {before} = splitAtAgentAnchor('可以并行。\n[');
		expect(before).toBe('可以并行。');
		expect(before).not.toContain('[');
	});

	it('falls back to --- for legacy transcripts', () => {
		const text = '说明A\n\n---\n\n汇总B';
		const {before, after, anchored} = splitAtAgentAnchor(text);
		expect(anchored).toBe(true);
		expect(before).toBe('说明A');
		expect(after).toBe('汇总B');
	});
});
