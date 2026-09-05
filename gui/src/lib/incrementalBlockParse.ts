import {parseMarkdownIntoBlocks} from 'streamdown';

/**
 * 增量分块：长文流式时避免每帧对全文跑 marked lex（O(全文)/帧，约 0.4ms/千字）。
 *
 * 原理：流式文本是追加式的，已「封口」的块不会再变化。缓存除最后一块外的
 * 全部块，每帧只对「最后一块起点之后的新增区」重新分块，再拼回。
 * 已封块不会以未闭合围栏结尾（streamdown 的合并规则会让后续 token 持续
 * 并入未闭合围栏块），因此对尾部切片分块与全文分块等价。
 *
 * 特判：streamdown 全量解析在文本含脚注语法（[^ref]）时会把整篇当单块，
 * 这里逐字复刻该行为——出现脚注时退回全量解析并清空缓存。
 */

const FOOTNOTE_REF_RE = /\[\^[\w-]{1,200}\](?!:)/;
const FOOTNOTE_DEF_RE = /\[\^[\w-]{1,200}\]:/;

export type BlockParseFn = (markdown: string) => string[];

export function createIncrementalBlockParse(
	parse: BlockParseFn = parseMarkdownIntoBlocks,
): BlockParseFn {
	let cacheText = '';
	let done: string[] = [];
	let doneOffset = 0;
	let lastResult: string[] = [];

	return function incrementalParse(text: string): string[] {
		if (text === cacheText) {
			return lastResult;
		}
		if (FOOTNOTE_REF_RE.test(text) || FOOTNOTE_DEF_RE.test(text)) {
			cacheText = text;
			done = [];
			doneOffset = 0;
			lastResult = parse(text);
			return lastResult;
		}
		if (!text.startsWith(cacheText)) {
			done = [];
			doneOffset = 0;
		}
		const tail = text.slice(doneOffset);
		const tailBlocks = parse(tail);
		const newDone = tailBlocks.slice(0, -1);
		if (newDone.length > 0) {
			done = done.concat(newDone);
			doneOffset += newDone.reduce((sum, block) => sum + block.length, 0);
		}
		cacheText = text;
		lastResult = done.concat(tailBlocks.slice(-1));
		return lastResult;
	};
}
