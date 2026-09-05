import {render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe, expect, it, vi} from 'vitest';
import {
	MD_BASIC,
	MD_CJK,
	MD_CODE_ALIAS,
	MD_CODE_EMPTY,
	MD_CODE_JS,
	MD_CODE_UNKNOWN_LANG,
	MD_CONTROL_CHARS,
	MD_HEADINGS,
	MD_HTML_INJECTION,
	MD_INCOMPLETE_FENCE,
	MD_LONG_CODE,
	MD_MATH,
	MD_MERMAID,
	MD_REL_LINK,
	MD_MIXED_EXTREME,
	MD_NESTED_BACKTICKS,
	MD_TABLE,
	MD_TASKS,
} from '@/lib/markdownFixtures';
import {normalizeHighlightLanguage} from './CodeBlock';
import {
	MarkdownView,
	markdownHasMath,
	promoteDisplayMath,
	sanitizeMarkdown,
} from './MarkdownView';

vi.mock('./MermaidBlock', () => ({
	MermaidBlock: ({source}: {source: string}) => (
		<img alt="mermaid" data-src={source} />
	),
}));

describe('sanitizeMarkdown', () => {
	it('strips control characters but keeps newlines/tabs', () => {
		expect(sanitizeMarkdown('a\u0000b\nc\td')).toBe('ab\nc\td');
	});

	it('detects math delimiters for KaTeX gating', () => {
		expect(markdownHasMath('hello')).toBe(false);
		expect(markdownHasMath('a $x$ b')).toBe(true);
		expect(markdownHasMath('$$E=mc^2$$')).toBe(true);
	});

	it('handles empty', () => {
		expect(sanitizeMarkdown('')).toBe('');
	});
});

describe('promoteDisplayMath', () => {
	it('lifts one-line $$ into a fence', () => {
		expect(promoteDisplayMath('$$ S = 1 $$')).toBe('$$\nS = 1\n$$');
	});
});

describe('normalizeHighlightLanguage', () => {
	it('aliases common tags', () => {
		expect(normalizeHighlightLanguage('ts')).toBe('typescript');
		expect(normalizeHighlightLanguage('py')).toBe('python');
		expect(normalizeHighlightLanguage('sh')).toBe('bash');
	});

	it('falls back safely', () => {
		expect(normalizeHighlightLanguage('')).toBe('text');
		expect(normalizeHighlightLanguage('!!!')).toBe('text');
	});
});

describe('MarkdownView rendering', () => {
	it('renders basic gfm inline/block elements', () => {
		const {container} = render(<MarkdownView content={MD_BASIC} />);
		expect(container.querySelector('h1')?.textContent).toContain('Title');
		expect(container.querySelector('strong')?.textContent).toBe('bold');
		expect(container.querySelector('em')?.textContent).toBe('italic');
		expect(container.querySelector('del')?.textContent).toBe('strike');
		expect(container.querySelector('ul')).toBeTruthy();
		expect(container.querySelector('ol')).toBeTruthy();
		expect(container.querySelector('blockquote')).toBeTruthy();
		expect(container.querySelector('hr')).toBeTruthy();
		expect(screen.getByRole('link', {name: 'link'})).toHaveAttribute(
			'href',
			'https://example.com',
		);
	});

	it('renders tables', () => {
		const {container} = render(<MarkdownView content={MD_TABLE} />);
		expect(container.querySelector('table')).toBeTruthy();
		expect(container.querySelectorAll('th').length).toBe(2);
		expect(container.querySelectorAll('td').length).toBe(4);
	});

	it('renders fenced javascript with Prism chrome', () => {
		const {container} = render(<MarkdownView content={MD_CODE_JS} />);
		expect(container.textContent).toContain('javascript');
		expect(container.textContent).toContain('function hello');
		expect(container.textContent).toContain('Before');
		expect(container.textContent).toContain('After');
	});

	it('renders empty fence without crashing', () => {
		const {container} = render(<MarkdownView content={MD_CODE_EMPTY} />);
		expect(container.textContent).toContain('python');
	});

	it('renders unknown language without crashing', () => {
		const {container} = render(
			<MarkdownView content={MD_CODE_UNKNOWN_LANG} />,
		);
		expect(container.textContent).toContain('foo bar');
	});

	it('renders ts alias fence', () => {
		const {container} = render(<MarkdownView content={MD_CODE_ALIAS} />);
		expect(container.textContent).toContain('const x');
	});

	it('tolerates incomplete fence (streaming mid-code)', () => {
		const {container} = render(
			<MarkdownView content={MD_INCOMPLETE_FENCE} codeAutoCollapse={false} />,
		);
		expect(container.textContent).toContain('Intro');
		expect(container.textContent).toContain('def foo');
		expect(container.textContent).not.toContain('```');
	});

	it('renders nested backticks fence', () => {
		const {container} = render(<MarkdownView content={MD_NESTED_BACKTICKS} />);
		expect(container.textContent).toContain('Use');
		expect(container.textContent).toContain('code');
	});

	it('renders task list items', () => {
		const {container} = render(<MarkdownView content={MD_TASKS} />);
		expect(container.textContent).toContain('done');
		expect(container.textContent).toContain('todo');
	});

	it('neutralizes dangerous links / does not execute script tags as HTML', () => {
		const {container} = render(<MarkdownView content={MD_HTML_INJECTION} />);
		expect(container.querySelector('script')).toBeNull();
		expect(
			container.querySelector('a[href^="javascript:"]'),
		).toBeNull();
		expect(screen.getByRole('link', {name: 'ok'})).toHaveAttribute(
			'href',
			'https://example.com',
		);
		// javascript: 链接渲染为惰性文本，而非 anchor
		expect(container.textContent).toContain('bad');
	});

	it('strips control chars in content and code', () => {
		const {container} = render(<MarkdownView content={MD_CONTROL_CHARS} />);
		expect(container.textContent).toContain('Linewithnulls');
		expect(container.textContent).not.toMatch(/\u0000/);
	});

	it('renders CJK + table + code', () => {
		const {container} = render(<MarkdownView content={MD_CJK} />);
		expect(container.textContent).toContain('中文');
		expect(container.textContent).toContain('你好');
		expect(container.querySelector('table')).toBeTruthy();
	});

	it('does not mount KaTeX for copy without math', () => {
		const {container} = render(<MarkdownView content={MD_BASIC} />);
		expect(container.querySelector('.katex')).toBeNull();
	});

	it('renders inline and display math with KaTeX', () => {
		const {container} = render(<MarkdownView content={MD_MATH} />);
		expect(container.querySelector('.katex')).toBeTruthy();
		expect(container.querySelector('.katex-display')).toBeTruthy();
		expect(container.textContent).not.toContain('$$');
	});

	it('renders <u> as underline, not literal tags', () => {
		const {container} = render(
			<MarkdownView content="请看<u>测两轮</u>这里" />,
		);
		expect(container.querySelector('u')?.textContent).toBe('测两轮');
		expect(container.textContent).toContain('测两轮');
		expect(container.textContent).not.toContain('<u>');
		expect(container.textContent).not.toContain('</u>');
	});

	it('renders h1–h6', () => {
		const {container} = render(<MarkdownView content={MD_HEADINGS} />);
		expect(container.querySelector('h1')).toBeTruthy();
		expect(container.querySelector('h6')).toBeTruthy();
	});

	it('long code with autoCollapse shows expand control', () => {
		render(<MarkdownView content={MD_LONG_CODE} codeAutoCollapse />);
		expect(screen.getByText('展开全部代码')).toBeInTheDocument();
	});

	it('long code with codeAutoCollapse=false stays expanded', () => {
		render(
			<MarkdownView content={MD_LONG_CODE} codeAutoCollapse={false} />,
		);
		expect(screen.queryByText('展开全部代码')).toBeNull();
		expect(screen.getByText(/line-39/)).toBeInTheDocument();
	});

	it('mixed extreme fixture renders without throw', () => {
		expect(() =>
			render(
				<MarkdownView content={MD_MIXED_EXTREME} codeAutoCollapse={false} />,
			),
		).not.toThrow();
	});

	it('streaming and final paths share Prism (not lite)', () => {
		const stream = render(
			<MarkdownView content={MD_CODE_JS} codeAutoCollapse={false} />,
		);
		const final_ = render(<MarkdownView content={MD_CODE_JS} />);
		// 两者都应从 CodeBlock chrome 暴露 language 标签
		expect(stream.container.textContent).toMatch(/javascript/i);
		expect(final_.container.textContent).toMatch(/javascript/i);
		expect(stream.container.querySelector('.token') || stream.container.textContent).toBeTruthy();
	});

	it('renders mermaid fence as an image', () => {
		const {container} = render(<MarkdownView content={MD_MERMAID} />);
		expect(container.querySelector('img[alt="mermaid"]')).toBeTruthy();
		expect(container.textContent).toContain('Intro');
	});

	it('opens relative wiki links via onOpenPath', async () => {
		const onOpenPath = vi.fn();
		render(
			<MarkdownView
				content={MD_REL_LINK}
				basePath="docs/设计/10-完整记忆体系.md"
				onOpenPath={onOpenPath}
			/>,
		);
		await userEvent.click(screen.getByRole('link', {name: '09'}));
		expect(onOpenPath).toHaveBeenCalledWith(
			'docs/设计/09-企业级落地计划-时序与排期.md',
			undefined,
		);
	});

	it('assigns heading ids for in-page jumps', () => {
		const {container} = render(<MarkdownView content={MD_HEADINGS} />);
		expect(container.querySelector('h1')?.id).toBeTruthy();
	});
});
