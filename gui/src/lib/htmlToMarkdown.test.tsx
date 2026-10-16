import {renderDeferred} from '@/test/renderDeferred';
import {describe, expect, it, vi} from 'vitest';
import {MarkdownView} from '@/components/MarkdownView';
import {
	MD_BASIC,
	MD_CODE_JS,
	MD_HEADINGS,
	MD_MERMAID,
	MD_TABLE,
	MD_TASKS,
} from '@/lib/markdownFixtures';
import {htmlToMarkdown} from './htmlToMarkdown';

vi.mock('@/components/MermaidBlock', () => ({
	MermaidBlock: ({source}: {source: string}) => (
		<img alt="mermaid" data-src={source} />
	),
}));

function fromHtml(html: string): string {
	const root = document.createElement('div');
	root.innerHTML = html;
	return htmlToMarkdown(root);
}

async function fromMarkdown(md: string): Promise<string> {
	const {container} = await renderDeferred(
		<MarkdownView content={md} className="xy-md-doc" editable />,
	);
	const root = container.querySelector('.xy-md-doc');
	if (!(root instanceof HTMLElement)) {
		throw new Error('missing markdown root');
	}
	return htmlToMarkdown(root);
}

describe('htmlToMarkdown', () => {
	it('serializes headings, emphasis, lists, quote, link, hr', async () => {
		const html = `
			<h1>Title</h1>
			<p>Paragraph with <strong>bold</strong>, <em>italic</em>, <del>strike</del>, and <code>inline</code>.</p>
			<ul><li>list a</li><li>list b</li></ul>
			<ol><li>one</li><li>two</li></ol>
			<blockquote><p>quote line</p></blockquote>
			<hr>
			<p><a href="https://example.com">link</a></p>
		`;
		const out = fromHtml(html);
		expect(out).toContain('# Title');
		expect(out).toContain('**bold**');
		expect(out).toContain('*italic*');
		expect(out).toContain('~~strike~~');
		expect(out).toContain('`inline`');
		expect(out).toContain('- list a');
		expect(out).toContain('1. one');
		expect(out).toContain('> quote line');
		expect(out).toContain('[link](https://example.com)');
		expect(out).toContain('---');
	});

	it('keeps underline as source tags but roundtrips through render', async () => {
		expect(fromHtml('<p>请看<u>测两轮</u>这里</p>')).toContain('<u>测两轮</u>');
		expect(await fromMarkdown('请看<u>测两轮</u>这里')).toContain('<u>测两轮</u>');
	});

	it('serializes tables and task lists', async () => {
		const html = `
			<table>
				<tr><th>A</th><th>B</th></tr>
				<tr><td>1</td><td>2</td></tr>
			</table>
			<ul>
				<li><input type="checkbox" checked> done</li>
				<li><input type="checkbox"> todo</li>
			</ul>
		`;
		const out = fromHtml(html);
		expect(out).toContain('| A | B |');
		expect(out).toContain('| --- | --- |');
		expect(out).toContain('| 1 | 2 |');
		expect(out).toContain('- [x] done');
		expect(out).toContain('- [ ] todo');
	});

	it('uses data-md-code for fenced blocks', async () => {
		const html = `<p>Before</p><div data-md-code="const x = 1;" data-md-fence="ts"></div>`;
		const out = fromHtml(html);
		expect(out).toContain('```ts');
		expect(out).toContain('const x = 1;');
	});

	it('roundtrips rendered MarkdownView for basic gfm', async () => {
		const out = await fromMarkdown(MD_BASIC);
		expect(out).toContain('# Title');
		expect(out).toContain('**bold**');
		expect(out).toContain('*italic*');
		expect(out).toContain('~~strike~~');
		expect(out).toContain('`inline`');
		expect(out).toContain('- list a');
		expect(out).toContain('1. one');
		expect(out).toContain('> quote line');
		expect(out).toContain('[link](https://example.com)');
	});

	it('roundtrips headings, tables, tasks, code, mermaid', async () => {
		expect(await fromMarkdown(MD_HEADINGS)).toContain('###### H6');
		expect(await fromMarkdown(MD_TABLE)).toMatch(/\| A \| B \|/);
		expect(await fromMarkdown(MD_TASKS)).toContain('- [x] done');
		expect(await fromMarkdown(MD_TASKS)).toContain('- [ ] todo');
		const code = await fromMarkdown(MD_CODE_JS);
		expect(code).toContain('```javascript');
		expect(code).toContain('function hello');
		const mermaid = await fromMarkdown(MD_MERMAID);
		expect(mermaid).toContain('```mermaid');
		expect(mermaid).toContain('flowchart LR');
	});

	it('picks up in-place text edits', async () => {
		const {container} = await renderDeferred(
			<MarkdownView content={'# Old\n\nHi'} className="xy-md-doc" editable />,
		);
		const html = container.innerHTML;
		const h1 = container.querySelector('h1');
		const p = container.querySelector('p');
		if (!h1 || !p) {
			throw new Error(`missing blocks html=${html}`);
		}
		h1.textContent = 'NewHead';
		p.textContent = 'Hi there';
		const root = container.querySelector('.xy-md-doc') as HTMLElement;
		const out = htmlToMarkdown(root);
		expect(out).toContain('# NewHead');
		expect(out).toContain('Hi there');
	});
});

describe('htmlToMarkdown 往返等式补强（写回通道结构性保真）', () => {
	it('嵌套列表整段等式往返', async () => {
		expect((await fromMarkdown('- a\n  - b\n- c')).trimEnd()).toBe('- a\n  - b\n- c');
	});

	it('围栏内嵌反引号时外层自动加长（fenceWrap n+1）', async () => {
		const md = '````\n```\ninner\n```\n````';
		expect((await fromMarkdown(md)).trimEnd()).toBe(md);
	});

	it('链接 title 存活往返（渲染层 anchor 带 title + 序列化写回）', async () => {
		const md = '[标题](https://example.com "提示")';
		expect((await fromMarkdown(md)).trimEnd()).toBe(md);
	});
});
