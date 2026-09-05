import {describe, expect, it} from 'vitest';
import {looksLikeMarkdown} from './chatMarkdown';

describe('looksLikeMarkdown', () => {
	it('flags block syntax on any line', () => {
		expect(looksLikeMarkdown('前言：\n- 第一条\n- 第二条')).toBe(true);
		expect(looksLikeMarkdown('看这里：\n1. 甲\n2. 乙')).toBe(true);
		expect(looksLikeMarkdown('开头\n## 小标题')).toBe(true);
		expect(looksLikeMarkdown('引用如下\n> 引用内容')).toBe(true);
	});

	it('flags fenced code', () => {
		expect(looksLikeMarkdown('```ts\nconst a = 1;\n```')).toBe(true);
		expect(looksLikeMarkdown('看代码：\n~~~\nfoo\n~~~')).toBe(true);
	});

	it('flags GFM table delimiter rows', () => {
		expect(looksLikeMarkdown('| a | b |\n| --- | --- |\n| 1 | 2 |')).toBe(
			true,
		);
	});

	it('flags inline syntax anywhere in the text', () => {
		expect(looksLikeMarkdown('这是 **重点** 内容')).toBe(true);
		expect(looksLikeMarkdown('跑一下 `npm run dev`')).toBe(true);
		expect(looksLikeMarkdown('标记 ~~废弃~~ 了')).toBe(true);
		expect(looksLikeMarkdown('见 [文档](https://example.com)')).toBe(true);
		expect(looksLikeMarkdown('图 ![截图](https://example.com/a.png)')).toBe(
			true,
		);
	});

	it('keeps plain text plain', () => {
		expect(looksLikeMarkdown('')).toBe(false);
		expect(looksLikeMarkdown('第一行\n第二行')).toBe(false);
		expect(looksLikeMarkdown('3 * 4 * 5 等于 60')).toBe(false);
		expect(looksLikeMarkdown('变量 user_name_here 保持原样')).toBe(false);
		expect(looksLikeMarkdown('#话题标签 不算标题')).toBe(false);
		expect(looksLikeMarkdown('价格 $5 和 $10')).toBe(false);
		expect(looksLikeMarkdown('路径 D:\\lea\\xyai')).toBe(false);
		expect(looksLikeMarkdown('普通句子，带标点。')).toBe(false);
	});

	it('flags hr and standalone emphasis markers conservatively', () => {
		expect(looksLikeMarkdown('上面\n---\n下面')).toBe(true);
		expect(looksLikeMarkdown('*强调*开头的一行')).toBe(true);
	});
});
