import {describe, expect, it} from 'vitest';
import remend from 'remend';
import {createIncrementalRemend} from './incrementalRemend';
import {xyRemendHandlers} from './streamdownRemend';

const OPTIONS = {handlers: xyRemendHandlers};

/** 模拟打字机追加式推进，逐帧对比增量 remend 与全量 remend 的输出。 */
function collectFrames(doc: string): string[] {
	const frames: string[] = [];
	let cut = 1;
	let step = 1;
	while (cut < doc.length) {
		frames.push(doc.slice(0, cut));
		cut += step;
		step = step >= 7 ? 1 : step + 1;
	}
	frames.push(doc);
	return frames;
}

function expectIncrementalMatchesFull(doc: string) {
	const incremental = createIncrementalRemend(OPTIONS);
	const frames = collectFrames(doc);
	for (const frame of frames) {
		expect(incremental(frame)).toBe(remend(frame, OPTIONS));
	}
}

describe('createIncrementalRemend', () => {
	it('matches full remend on streaming prose paragraphs', () => {
		expectIncrementalMatchesFull(
			'## 标题一\n\n这是第一段正文内容，包含一些文字用来模拟流式输入的过程。\n\n## 标题二\n\n第二段正文，同样足够长，确保产生多个安全空行边界。\n\n第三段收尾内容。',
		);
	});

	it('matches full remend while bold is being typed then closed', () => {
		expectIncrementalMatchesFull(
			'前面文字 **加粗内容** 已经闭合。\n\n第二段正文内容继续输出。',
		);
	});

	it('keeps unclosed pre-boundary markers raw instead of closing at stream end', () => {
		// 已知偏差：`**` 跨过空行仍未闭合时，全量 remend 会把收尾追加到全文
		// 最末（中间整段被渲染成粗体、闭合瞬间弹回）；增量版保持前文原样，
		// 直到 `**` 真正闭合，流式观感更稳定。
		const incremental = createIncrementalRemend(OPTIONS);
		const out = incremental('前面文字 **加粗内容正在输入，\n\n后续第二段继续。');
		expect(out).toBe('前面文字 **加粗内容正在输入，\n\n后续第二段继续。');
	});

	it('matches full remend while inline code is typed', () => {
		expectIncrementalMatchesFull(
			'运行 `npm run dev 看到半截代码标记。\n\n下一段正文继续。',
		);
		expectIncrementalMatchesFull(
			'运行 `npm run dev` 命令即可。\n\n下一段正文继续输出内容。',
		);
	});

	it('matches full remend across opening and closing code fences', () => {
		const doc = [
			'第一段说明文字。',
			'',
			'```ts',
			'const a = 1;',
			'const b = 2;',
			'```',
			'',
			'围栏后的说明文字，继续输出一些内容让文本变长。',
		].join('\n');
		expectIncrementalMatchesFull(doc);
	});

	it('matches full remend while a code fence is still open at the tail', () => {
		expectIncrementalMatchesFull(
			'说明文字。\n\n```ts\nconst a = 1;\nconst b = 2;\nconst c = 3;',
		);
	});

	it('matches full remend while an incomplete link is at the tail', () => {
		expectIncrementalMatchesFull(
			'参考 [文档](https://example.com/a) 与 [另一个链接](https://exa',
		);
	});

	it('matches full remend when a table is being streamed', () => {
		const doc = [
			'表格说明。',
			'',
			'| 列甲 | 列乙 |',
			'| --- | --- |',
			'| 1 | 2 |',
			'| 3 | 4 |',
			'',
			'表格后的正文内容，继续输出。',
		].join('\n');
		expectIncrementalMatchesFull(doc);
		expectIncrementalMatchesFull(
			'表格说明。\n\n| 列甲 | 列乙 |\n| --- | --- |\n| 1 | 2 |',
		);
	});

	it('matches full remend with global tilde and comparison escapes', () => {
		expectIncrementalMatchesFull(
			'波形记号 字~字 出现在第一段。\n\n- > 25 是列表里的比较符。\n\n后续正文继续输出内容。',
		);
	});

	it('matches full remend when text ends exactly on a blank line', () => {
		expectIncrementalMatchesFull('第一段结束。\n\n');
	});

	it('stays correct when content is rewritten (non-append)', () => {
		const incremental = createIncrementalRemend(OPTIONS);
		incremental('第一版很长的内容。\n\n第二段也有一定长度，用于建立扫描状态。');
		// 回溯替换：走全量重扫回退，输出仍须正确
		expect(incremental('完全不同的 **新内容')).toBe(
			remend('完全不同的 **新内容', OPTIONS),
		);
	});

	it('reuses cached output for identical input', () => {
		const incremental = createIncrementalRemend(OPTIONS);
		const first = incremental('同样 **文本');
		expect(incremental('同样 **文本')).toBe(first);
	});
});
