import {describe, expect, it} from 'vitest';
import {resolveMediaRefsInMarkdown} from './markdownMediaRefs';

const REF = 'xeyo-media://' + 'a'.repeat(64);

describe('resolveMediaRefsInMarkdown（#13 渲染端归一化）', () => {
	it('图片引用改写为后端地址', () => {
		const out = resolveMediaRefsInMarkdown(`![截图](${REF})`);
		expect(out).toContain('![截图](/v1/media/aaaa');
		expect(out).not.toContain('xeyo-media://');
	});

	it('非 64hex / 非图片形态原样保留', () => {
		expect(resolveMediaRefsInMarkdown('![x](xeyo-media://short)')).toContain(
			'xeyo-media://short',
		);
		expect(resolveMediaRefsInMarkdown(`[链接](${REF})`)).toContain(REF);
		expect(resolveMediaRefsInMarkdown('无媒体文本')).toBe('无媒体文本');
	});

	it('多张图片逐处改写', () => {
		const ref2 = 'xeyo-media://' + 'b'.repeat(64);
		const out = resolveMediaRefsInMarkdown(`![a](${REF}) 与 ![b](${ref2})`);
		expect((out.match(/\/v1\/media\//g) ?? []).length).toBe(2);
	});
});
