import {describe, expect, it} from 'vitest';
import {parseMarkdownIntoBlocks} from 'streamdown';
import {
	parseStaticBlocks,
	prepareStaticMarkdown,
	promoteDisplayMath,
	sanitizeMarkdown,
} from './markdownStaticCache';

const SAMPLES = [
	'# 标题\n\n段落一。\n\n- 列表项 1\n- 列表项 2\n',
	'```ts\nconst a = 1;\n```\n\n后文 `code` 与 **加粗**。\n',
	'未闭合围栏：\n```python\nprint(1)\n',
	'脚注引用[^ref]与定义\n\n[^ref]: 注释内容\n',
	'| a | b |\n| --- | --- |\n| 1 | 2 |\n\n> 引用\n',
	'$$\nE = mc^2\n$$\n',
	'',
];

describe('markdownStaticCache', () => {
	it('parseStaticBlocks 输出与 parseMarkdownIntoBlocks 逐字节相同（记忆化透明）', () => {
		for (const sample of SAMPLES) {
			expect(parseStaticBlocks(sample)).toEqual(parseMarkdownIntoBlocks(sample));
		}
	});

	it('重复调用命中缓存：深度相等且每次返回新数组（缓存不被外部分沾）', () => {
		const first = parseStaticBlocks(SAMPLES[1]!);
		const second = parseStaticBlocks(SAMPLES[1]!);
		expect(second).toEqual(first);
		expect(second).not.toBe(first);
		// 调用方改写返回的数组不得污染缓存。
		second.length = 0;
		expect(parseStaticBlocks(SAMPLES[1]!)).toEqual(first);
	});

	it('prepareStaticMarkdown 与 promoteDisplayMath(sanitizeMarkdown(x)) 相同', () => {
		const cases = [
			...SAMPLES,
			'a\u0000b\nc\td',
			'$$ S = 1 $$',
			'前文\n$$x+y$$\n后文',
			'无控制字符普通文本',
		];
		for (const c of cases) {
			expect(prepareStaticMarkdown(c)).toBe(
				promoteDisplayMath(sanitizeMarkdown(c)),
			);
		}
	});

	it('sanitizeMarkdown / promoteDisplayMath 行为保持原语义', () => {
		expect(sanitizeMarkdown('a\u0000b\nc\td')).toBe('ab\nc\td');
		expect(sanitizeMarkdown('')).toBe('');
		expect(promoteDisplayMath('$$ S = 1 $$')).toBe('$$\nS = 1\n$$');
		// 不含 $$ 时原样返回。
		expect(promoteDisplayMath('plain')).toBe('plain');
		// 行内 $ 不提升。
		expect(promoteDisplayMath('a $x$ b')).toBe('a $x$ b');
	});
});
