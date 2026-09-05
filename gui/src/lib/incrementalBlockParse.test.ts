import {describe, expect, it} from 'vitest';
import {parseMarkdownIntoBlocks} from 'streamdown';
import {createIncrementalBlockParse} from './incrementalBlockParse';

/** 模拟打字机追加式推进，逐帧对比增量分块与全量分块。 */
function expectIncrementalMatchesFull(doc: string) {
	const incremental = createIncrementalBlockParse();
	let cut = 1;
	let step = 1;
	while (cut < doc.length) {
		const frame = doc.slice(0, cut);
		expect(JSON.stringify(incremental(frame))).toBe(
			JSON.stringify(parseMarkdownIntoBlocks(frame)),
		);
		cut += step;
		step = step >= 9 ? 1 : step + 1;
	}
	expect(JSON.stringify(incremental(doc))).toBe(
		JSON.stringify(parseMarkdownIntoBlocks(doc)),
	);
}

describe('createIncrementalBlockParse', () => {
	it('matches full parse on streaming prose with headings and lists', () => {
		const doc = [
			'## 标题一',
			'',
			'第一段正文内容，包含足够的文字用于换行测试换行测试。',
			'',
			'- 列表项一：内容较长以便观察块边界稳定不漂移不漂移',
			'- 列表项二：继续补充一些文字让列表有两项内容',
			'',
			'## 标题二',
			'',
			'第二段正文收尾内容，同样保持一定长度。',
		].join('\n\n');
		expectIncrementalMatchesFull(doc);
	});

	it('matches full parse while a code fence opens, fills and closes', () => {
		const doc = [
			'说明文字。',
			'',
			'```ts',
			'const a = 1;',
			'const b = 2;',
			'const c = 3;',
			'```',
			'',
			'围栏后的说明文字继续输出。',
		].join('\n\n');
		expectIncrementalMatchesFull(doc);
	});

	it('matches full parse while the last block keeps growing', () => {
		const doc = `${'这是同一段落持续追加的文字。'.repeat(30)}`;
		expectIncrementalMatchesFull(doc);
	});

	it('matches full parse when text ends exactly on a blank line', () => {
		expectIncrementalMatchesFull('第一段结束。\n\n');
	});

	it('treats footnote syntax as a single whole-doc block like full parse', () => {
		const incremental = createIncrementalBlockParse();
		const before = '前文内容足够长，用于建立多块缓存状态。\n\n第二段正文。';
		incremental(before);
		const withFootnote = `${before}\n\n脚注引用[^1] 出现。`;
		expect(incremental(withFootnote)).toEqual(
			parseMarkdownIntoBlocks(withFootnote),
		);
		const grown = `${withFootnote}继续追加的文字。`;
		expect(incremental(grown)).toEqual(parseMarkdownIntoBlocks(grown));
	});

	it('falls back to full reparse when content is rewritten', () => {
		const incremental = createIncrementalBlockParse();
		incremental('第一版内容比较长的一段话。\n\n第二段也保持长度。');
		const rewritten = '完全不同的 **新内容开始';
		expect(incremental(rewritten)).toEqual(parseMarkdownIntoBlocks(rewritten));
	});

	it('reuses the same result array for identical input', () => {
		const incremental = createIncrementalBlockParse();
		const first = incremental('一段内容。\n\n第二段。');
		expect(incremental('一段内容。\n\n第二段。')).toBe(first);
	});
});
