import {describe, expect, it, vi} from 'vitest';
import {parseMarkdownIntoBlocks} from 'streamdown';
import {parseStaticBlocks} from './markdownStaticCache';

vi.mock('streamdown', () => ({parseMarkdownIntoBlocks: vi.fn((text: string) => [text])}));

describe('Markdown 缓存文本预算', () => {
	it('30 篇十万字文档超过总预算后释放旧缓存，并保留近期命中', () => {
		const documents = Array.from({length: 30}, (_, i) => `${i}`.padEnd(100_000, 'x'));
		for (const doc of documents) expect(parseStaticBlocks(doc)).toEqual([doc]);
		vi.mocked(parseMarkdownIntoBlocks).mockClear();
		expect(parseStaticBlocks(documents.at(-1)!)).toEqual([documents.at(-1)!]);
		expect(parseMarkdownIntoBlocks).not.toHaveBeenCalled();
		expect(parseStaticBlocks(documents[0])).toEqual([documents[0]]);
		console.info('PERF Markdown oldest entry recomputations after budget exceeded:', vi.mocked(parseMarkdownIntoBlocks).mock.calls.length);
		expect(parseMarkdownIntoBlocks).toHaveBeenCalledTimes(1);
	});
});
