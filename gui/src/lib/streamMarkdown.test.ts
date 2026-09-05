import {describe, expect, it} from 'vitest';
import {
	balanceInlineMd,
	hasStreamMarkdownSyntax,
	parseStreamTable,
	splitPipeCells,
	splitStreamMarkdown,
	splitStreamMarkdownIncremental,
	streamNeedsFastTypewriter,
	scanPendingTable,
	stripGrowingFenceCloser,
} from './streamMarkdown';

describe('balanceInlineMd', () => {
	it('closes odd bold and code ticks', () => {
		expect(balanceInlineMd('**ab')).toBe('**ab**');
		expect(balanceInlineMd('say `x')).toBe('say `x`');
	});

	it('closes inline emphasis and strikethrough before live render', () => {
		expect(balanceInlineMd('*em')).toBe('*em*');
		expect(balanceInlineMd('_it')).toBe('_it_');
		expect(balanceInlineMd('~~strike')).toBe('~~strike~~');
	});

	it('does not phantom-close list bullets or arithmetic stars', () => {
		// 星号列表项：以前会被补出尾随 “*”，行完成后又消失 → 抖动。
		expect(balanceInlineMd('* 项目')).toBe('* 项目');
		expect(balanceInlineMd('- [ ] 任务')).toBe('- [ ] 任务');
		// 乘号两侧空白，不是强调。
		expect(balanceInlineMd('2 * 3')).toBe('2 * 3');
		// 词内下划线是字面量。
		expect(balanceInlineMd('snake_case_name')).toBe('snake_case_name');
	});

	it('routes inline markers away from plain live chars', () => {
		expect(hasStreamMarkdownSyntax('*em')).toBe(true);
		expect(hasStreamMarkdownSyntax('_it')).toBe(true);
		expect(hasStreamMarkdownSyntax('~~strike')).toBe(true);
		expect(hasStreamMarkdownSyntax('[link](url')).toBe(true);
	});

	it('treats list/heading as block markdown, not raw live chars', () => {
		expect(hasStreamMarkdownSyntax('* 项目')).toBe(true);
		expect(hasStreamMarkdownSyntax('# 标题')).toBe(true);
		expect(hasStreamMarkdownSyntax('###')).toBe(true);
		expect(hasStreamMarkdownSyntax('- item')).toBe(true);
	});

	it('does not treat arithmetic stars or snake_case as markdown', () => {
		expect(hasStreamMarkdownSyntax('2 * 3')).toBe(false);
		expect(hasStreamMarkdownSyntax('snake_case_name')).toBe(false);
		expect(hasStreamMarkdownSyntax('plain text')).toBe(false);
	});
});

describe('splitStreamMarkdown', () => {
	it('parses a growing first line as live markdown, not raw tail', () => {
		expect(splitStreamMarkdown('Hel')).toEqual({
			head: '',
			live: 'Hel',
			fence: null,
			math: null,
			tablePending: null,
			table: null,
		});
	});

	it('commits complete lines and keeps the last as live', () => {
		expect(splitStreamMarkdown('Hello\nwor')).toEqual({
			head: 'Hello\n',
			live: 'wor',
			fence: null,
			math: null,
			tablePending: null,
			table: null,
		});
	});

	it('turns an unclosed fence into a code payload without backticks', () => {
		const src = 'Intro\n\n```js\nconst x = 1';
		expect(splitStreamMarkdown(src)).toEqual({
			head: 'Intro\n\n',
			live: '',
			fence: {lang: 'js', code: 'const x = 1'},
			math: null,
			tablePending: null,
			table: null,
		});
	});

	it('treats a fence opener-only line as empty code, not source', () => {
		expect(splitStreamMarkdown('```python')).toEqual({
			head: '',
			live: '',
			fence: {lang: 'python', code: ''},
			math: null,
			tablePending: null,
			table: null,
		});
	});

	it('commits a closed fence and keeps the following line live', () => {
		const src = '```js\nconst x = 1\n```\nnext';
		expect(splitStreamMarkdown(src)).toEqual({
			head: '```js\nconst x = 1\n```\n',
			live: 'next',
			fence: null,
			math: null,
			tablePending: null,
			table: null,
		});
	});

	it('holds unclosed display math without $$', () => {
		const src = 'Before\n$$\nE = mc';
		expect(splitStreamMarkdown(src)).toEqual({
			head: 'Before\n',
			live: '',
			fence: null,
			math: 'E = mc',
			tablePending: null,
			table: null,
		});
	});
});

describe('splitStreamMarkdown tables', () => {
	it('crystallizes the table as soon as the delimiter row shape completes', () => {
		// 分隔行一旦形状完整（哪怕还没等到换行），立即升级为真实表格块：
		// 流式期间列宽由 CSS 固定，后续加宽列数只改高度，不再横跳。
		expect(splitStreamMarkdown('| 表头 |\n| --')).toEqual({
			head: '',
			live: '',
			fence: null,
			math: null,
			tablePending: null,
			table: '| 表头 |\n| --',
		});
	});

	it('absorbs the whole table region once the delimiter row completes', () => {
		// 空尾：分隔行刚换行完成，整个区域立即结晶成表格块。
		expect(splitStreamMarkdown('| A | B |\n| --- | --- |\n')).toEqual({
			head: '',
			live: '',
			fence: null,
			math: null,
			tablePending: null,
			table: '| A | B |\n| --- | --- |\n',
		});
		// 生长中的数据行也直接进表格，不再悬在表格下面当裸段落。
		expect(
			splitStreamMarkdown('| A | B |\n| --- | --- |\n| 左 | 右'),
		).toEqual({
			head: '',
			live: '',
			fence: null,
			math: null,
			tablePending: null,
			table: '| A | B |\n| --- | --- |\n| 左 | 右',
		});
	});

	it('unbarred delimiter forms are recognized too', () => {
		expect(
			splitStreamMarkdown('A | B\n--- | ---\n| 1 |'),
		).toEqual({
			head: '',
			live: '',
			fence: null,
			math: null,
			tablePending: null,
			table: 'A | B\n--- | ---\n| 1 |',
		});
	});

	it('joins trailing prose into the flowing region until a blank line', () => {
		// 行后无空行直接接散文：区域保持开放，一并吸进同一个块；
		// remark 会按 GFM 规则自动断开表尾。增量与全量解析分区一致，
		// 不会出现逐帧翻转。
		expect(splitStreamMarkdown('| A | B |\n| --- | --- |\ntext')).toEqual({
			head: '',
			live: '',
			fence: null,
			math: null,
			tablePending: null,
			table: '| A | B |\n| --- | --- |\ntext',
		});
	});

	it('ignores pipe rows separated by blank lines and ignores fences', () => {
		const src = '| A | B |\n| --- | --- |\n\n看这个 ```js 围栏\nx';
		const parts = splitStreamMarkdown(src);
		// 空行已截断表格；后文不是完整结构，不应再产生 table 区。
		expect(parts.table).toBeNull();
	});

	it('completes fenced code between table regions without confusion', () => {
		const src = 'code:\n\n```ts\na\n```\n\n| X | Y |\n| - | - |\n| 1 ';
		expect(splitStreamMarkdown(src)).toEqual({
			head: 'code:\n\n```ts\na\n```\n\n',
			live: '',
			fence: null,
			math: null,
			tablePending: null,
			table: '| X | Y |\n| - | - |\n| 1 ',
		});
	});
});

describe('splitStableMarkdownBlocks', () => {
	it('splits ordinary paragraphs only at safe blank lines', async () => {
		const {splitStableMarkdownBlocks} = await import('./streamMarkdown');
		expect(splitStableMarkdownBlocks('a\n\nb\n')).toEqual(['a\n', 'b\n']);
	});

	it('keeps list and quote continuation together', async () => {
		const {splitStableMarkdownBlocks} = await import('./streamMarkdown');
		const source = '- a\n- b\n\n> note\n\nnext';
		expect(splitStableMarkdownBlocks(source)).toEqual([source]);
	});

	it('keeps fenced code and display math intact', async () => {
		const {splitStableMarkdownBlocks} = await import('./streamMarkdown');
		const source = 'intro\n\n```ts\nconst x = 1;\n```\n\n$$\nx^2\n$$\n\nend';
		expect(splitStableMarkdownBlocks(source)).toEqual([
			'intro\n',
			'```ts\nconst x = 1;\n```\n',
			'$$\nx^2\n$$\n',
			'end',
		]);
	});
});

describe('splitStreamMarkdownIncremental', () => {
	it('matches full parsing for ordinary appended text', async () => {
		let cache = splitStreamMarkdownIncremental('Hello\nwor', null);
		cache = splitStreamMarkdownIncremental('Hello\nworld', cache);
		expect(cache.parts).toEqual(splitStreamMarkdown('Hello\nworld'));
	});

	it('appends inside an open fence without rescanning the prefix', () => {
		let cache = splitStreamMarkdownIncremental('Intro\n\n```ts\nconst x', null);
		cache = splitStreamMarkdownIncremental('Intro\n\n```ts\nconst x = 1', cache);
		expect(cache.parts).toEqual(splitStreamMarkdown('Intro\n\n```ts\nconst x = 1'));
	});

	it('appends inside open display math and falls back when it closes', () => {
		let cache = splitStreamMarkdownIncremental('Before\n$$\nE =', null);
		cache = splitStreamMarkdownIncremental('Before\n$$\nE = mc', cache);
		expect(cache.parts).toEqual(splitStreamMarkdown('Before\n$$\nE = mc'));
		cache = splitStreamMarkdownIncremental('Before\n$$\nE = mc\n$$\nnext', cache);
		expect(cache.parts).toEqual(splitStreamMarkdown('Before\n$$\nE = mc\n$$\nnext'));
	});

	it('appends streaming table rows without re-splitting', () => {
		const base = '| A | B |\n| --- | --- |\n| r1 |';
		let cache = splitStreamMarkdownIncremental(base, null);
		expect(cache.parts.table).toBe(base);
		cache = splitStreamMarkdownIncremental(`${base} c1 | c2`, cache);
		cache = splitStreamMarkdownIncremental(`${base} c1 | c2\n| r2 | v`, cache);
		cache = splitStreamMarkdownIncremental(
			`${base} c1 | c2\n| r2 | v`,
			cache,
		);
		expect(cache.parts.table).toBe(`${base} c1 | c2\n| r2 | v`);
		expect(cache.parts.head).toBe('');
		expect(cache.parts.live).toBe('');
		// 与完整解析结果一致。
		expect(cache.parts).toEqual(
			splitStreamMarkdown(`${base} c1 | c2\n| r2 | v`),
		);
	});

	it('leaves table mode when a blank line ends the region', () => {
		const base = '| A | B |\n| --- | --- |\n| r1 |';
		let cache = splitStreamMarkdownIncremental(base, null);
		cache = splitStreamMarkdownIncremental(`${base}\n\n后续文字`, cache);
		expect(cache.parts).toEqual(splitStreamMarkdown(`${base}\n\n后续文字`));
		expect(cache.parts.table).toBeNull();
	});

	it('falls back to full parsing for replacement text', () => {
		const cache = splitStreamMarkdownIncremental('old', null);
		const next = splitStreamMarkdownIncremental('new', cache);
		expect(next.parts).toEqual(splitStreamMarkdown('new'));
	});

	it('prose then growing pipe header matches full parse (no live pipes)', () => {
		let cache = splitStreamMarkdownIncremental('Hello\n\n', null);
		cache = splitStreamMarkdownIncremental('Hello\n\n| A', cache);
		expect(cache.parts).toEqual(splitStreamMarkdown('Hello\n\n| A'));
		expect(cache.parts.live).toBe('');
		expect(cache.parts.tablePending).not.toBeNull();
		expect(cache.parts.live).not.toContain('|');
	});

	it('prose then growing delimiter matches full parse (no live pipes)', () => {
		const base = 'Hello\n\n| Name | Age |\n| ---';
		let cache = splitStreamMarkdownIncremental('Hello\n\n| Name | Age |\n', null);
		cache = splitStreamMarkdownIncremental(base, cache);
		expect(cache.parts).toEqual(splitStreamMarkdown(base));
		expect(cache.parts.live).toBe('');
		// 分隔行已成型 → 进 table 而非 live 明文
		expect(cache.parts.table).toBeTruthy();
		expect(cache.parts.tablePending).toBeNull();
	});
});

describe('streamNeedsFastTypewriter', () => {
	it('is true inside an open fence', () => {
		expect(streamNeedsFastTypewriter('```js\nconst x')).toBe(true);
	});

	it('is true for an established table', () => {
		expect(streamNeedsFastTypewriter('| A | B |\n| --- | --- |\n| 1 |')).toBe(true);
	});

	it('is false for plain prose', () => {
		expect(streamNeedsFastTypewriter('Hello world')).toBe(false);
	});
});

describe('parseStreamTable', () => {
	it('freezes headers and keeps a live last row', () => {
		const model = parseStreamTable('| A | B |\n| --- | --- |\n| 1 | tw');
		expect(model).not.toBeNull();
		expect(model!.headers).toEqual(['A', 'B']);
		expect(model!.rows).toEqual([]);
		expect(model!.liveRow).toEqual(['1', 'tw']);
	});

	it('commits completed body rows when a new line starts', () => {
		const model = parseStreamTable('| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 |');
		expect(model!.rows).toEqual([['1', '2']]);
		expect(model!.liveRow).toEqual(['3', '']);
	});

	it('shows an empty live row after a trailing newline', () => {
		const model = parseStreamTable('| A | B |\n| --- | --- |\n| 1 | 2 |\n');
		expect(model!.rows).toEqual([['1', '2']]);
		expect(model!.liveEmpty).toBe(true);
		expect(model!.liveRow).toEqual(['', '']);
	});
});

describe('splitPipeCells', () => {
	it('tolerates missing edge pipes', () => {
		expect(splitPipeCells('A | B')).toEqual(['A', 'B']);
		expect(splitPipeCells('| A | B |')).toEqual(['A', 'B']);
	});
});


describe('scanPendingTable', () => {
	it('hides a growing header as cell preview metadata', () => {
		const p = scanPendingTable('| A | B');
		expect(p).not.toBeNull();
		expect(p!.headers).toEqual(['A', 'B']);
		expect(p!.growingHeader).toBe(true);
	});

	it('keeps headers while delimiter is still growing', () => {
		const p = scanPendingTable('| A | B |\n|');
		expect(p).not.toBeNull();
		expect(p!.headers).toEqual(['A', 'B']);
		expect(p!.growingHeader).toBe(false);
	});

	it('splits pending away from established tables', () => {
		expect(scanPendingTable('| A | B |\n| --- | --- |\n| 1 |')).toBeNull();
	});
});

describe('stripGrowingFenceCloser', () => {
	it('holds one or two closing ticks so they never paint in code', () => {
		expect(stripGrowingFenceCloser('const x = 1\n`')).toEqual({
			code: 'const x = 1\n',
			closed: false,
		});
		expect(stripGrowingFenceCloser('const x = 1\n``')).toEqual({
			code: 'const x = 1\n',
			closed: false,
		});
	});

	it('flags a complete closer for full reparse', () => {
		expect(stripGrowingFenceCloser('const x = 1\n```').closed).toBe(true);
	});
});

describe('splitStreamMarkdown pending table', () => {
	it('does not leave pipe header in live/head prose', () => {
		const parts = splitStreamMarkdown('| Name | Age |\n|');
		expect(parts.live).toBe('');
		expect(parts.table).toBeNull();
		expect(parts.tablePending).toEqual({
			headers: ['Name', 'Age'],
			growingHeader: false,
		});
		expect(parts.head.includes('|')).toBe(false);
	});
});
