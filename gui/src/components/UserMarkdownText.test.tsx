import {render} from '@testing-library/react';
import {describe, expect, it} from 'vitest';
import {UserMarkdownText} from './UserMarkdownText';

describe('UserMarkdownText', () => {
	it('renders plain text with whitespace-pre-wrap and no markdown elements', () => {
		const {container} = render(
			<UserMarkdownText
				text={'第一行\n第二行 3 * 4'}
				className="xy-chat-text text-[15px]"
			/>,
		);
		const host = container.firstElementChild as HTMLElement;
		expect(host.className).toContain('whitespace-pre-wrap');
		expect(host.textContent).toBe('第一行\n第二行 3 * 4');
		expect(container.querySelector('strong')).toBeNull();
		expect(container.querySelector('ul')).toBeNull();
	});

	it('renders markdown text through the streamdown kernel', () => {
		const {container} = render(
			<UserMarkdownText
				text={'注意 **重点** 和 `code`'}
				className="xy-chat-text text-[15px]"
			/>,
		);
		expect(container.querySelector('strong')?.textContent).toBe('重点');
		expect(container.querySelector('code')?.textContent).toBe('code');
	});

	it('renders single newlines as hard breaks in markdown mode (chat口径)', () => {
		const {container} = render(
			<UserMarkdownText
				text={'- 第一种\n- 第二种\n后续说明第一行\n后续说明第二行'}
				className="xy-chat-text text-[15px]"
			/>,
		);
		expect(container.querySelector('ul')).toBeTruthy();
		expect(container.querySelectorAll('br').length).toBeGreaterThanOrEqual(1);
		expect(container.textContent).toContain('后续说明第一行');
	});

	it('keeps plain multi-line text without <br> nodes', () => {
		const {container} = render(
			<UserMarkdownText
				text={'第一行\n第二行'}
				className="xy-chat-text text-[15px]"
			/>,
		);
		expect(container.querySelectorAll('br')).toHaveLength(0);
	});
});
