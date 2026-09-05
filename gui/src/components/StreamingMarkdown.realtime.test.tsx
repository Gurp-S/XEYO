import {describe, expect, it} from 'vitest';
import {render} from '@testing-library/react';
import {StreamingMarkdown} from './StreamingMarkdown';

describe('StreamingMarkdown streamdown kernel', () => {
	it('renders heading from streaming text without hash source', () => {
		const {container} = render(
			<StreamingMarkdown text={'## 标题\n\n正文 **粗** 还在打'} />,
		);
		expect(container.querySelector('h2')?.textContent).toContain('标题');
		expect(container.querySelector('strong')?.textContent).toMatch(/粗/);
		expect(container.textContent).not.toContain('##');
	});

	it('growing bold does not show asterisks', () => {
		const {container} = render(
			<StreamingMarkdown text={'前面 **粗体还'} />,
		);
		expect(container.textContent).not.toContain('**');
		expect(container.querySelector('strong')).toBeTruthy();
	});

	it('unbalanced ticks must not dump raw markers', () => {
		const {container} = render(
			<StreamingMarkdown text={'说 `半截'} />,
		);
		expect(container.textContent).not.toContain('`');
		expect(container.querySelector('code')?.textContent).toContain('半截');
	});

	it('live heading hides hash markers', () => {
		const {container} = render(
			<StreamingMarkdown text={'## 正在写标题'} />,
		);
		expect(container.textContent).not.toContain('##');
		expect(container.textContent).toContain('正在写标题');
		expect(container.querySelector('.xy-streamdown-live')).toBeTruthy();
	});

	it('lone hash markers do not paint as source', () => {
		const {container} = render(<StreamingMarkdown text={'###'} />);
		expect(container.textContent).not.toContain('#');
	});

	it('plain upgrades to bold without raw markers', () => {
		const {container, rerender} = render(
			<StreamingMarkdown text={'前面'} />,
		);
		expect(container.textContent).toContain('前面');
		rerender(<StreamingMarkdown text={'前面 **粗'} />);
		expect(container.textContent).not.toContain('**');
		expect(container.querySelector('strong')).toBeTruthy();
	});

	it('prose then pipe header never paints pipe source', () => {
		const {container} = render(
			<StreamingMarkdown text={'Hello\n\n| A'} />,
		);
		expect(container.textContent).not.toMatch(/\|/);
	});

	it('final mode has no live class, no raw markers, no fade chars', () => {
		const {container} = render(
			<StreamingMarkdown
				text={'## 完成\n\n正文 **粗**'}
				final
				codeAutoCollapse
			/>,
		);
		expect(container.querySelector('h2')?.textContent).toContain('完成');
		expect(container.querySelector('strong')?.textContent).toContain('粗');
		expect(container.querySelector('.xy-streamdown-live')).toBeNull();
		expect(container.querySelectorAll('.xy-tail-fade').length).toBe(0);
		expect(container.querySelectorAll('.xy-char').length).toBe(0);
		expect(container.textContent).not.toContain('**');
		expect(container.textContent).not.toContain('##');
	});

	it('tail fade spans multiple blocks near the end', () => {
		const {container} = render(
			<StreamingMarkdown text={'第一段内容在这里\n\n第二段也在流'} />,
		);
		const chars = container.querySelectorAll('.xy-char');
		expect(chars.length).toBeGreaterThanOrEqual(1);
		expect(container.textContent).toContain('第一段');
		expect(container.textContent).toContain('第二段');
	});

	it('list renders item text without dash source prefix', () => {
		const {container} = render(
			<StreamingMarkdown text={'- 项目内容'} />,
		);
		expect(container.textContent).toContain('项目内容');
		expect(container.querySelector('li')).toBeTruthy();
		expect(container.textContent).not.toMatch(/^- /);
	});

	it('hr line does not paint --- as prose', () => {
		const {container} = render(
			<StreamingMarkdown text={'---'} />,
		);
		expect(container.querySelector('hr')).toBeTruthy();
		expect(container.textContent).not.toContain('---');
	});
});
