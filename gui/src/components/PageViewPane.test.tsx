import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it} from 'vitest';
import chatPageSrc from '../pages/ChatPage.tsx?raw';
import {PageViewPane} from './PageViewPane';

/**
 * 页面视图挂载壳（bug #5）：`shown` 必须参与可见性判定。
 * 少了它，新页面视图会以满不透明度硬切进来，盖在还在淡出的上一个页面视图上
 * （两块都是 absolute inset-0），两层半透明面板叠在一起。
 */

function paneProps(extra?: {active?: boolean; mounted?: boolean; shown?: boolean}) {
	return {
		active: extra?.active ?? true,
		mounted: extra?.mounted ?? true,
		shown: extra?.shown ?? true,
		label: '用量',
		children: <div data-testid="pane-body">内容</div>,
	};
}

function pane(): HTMLElement {
	const body = screen.getByTestId('pane-body');
	const el = body.parentElement;
	if (!el) {
		throw new Error('未渲染面板外壳');
	}
	return el;
}

afterEach(cleanup);

describe('PageViewPane 的入场态', () => {
	it('入场帧未满时保持隐藏（opacity-0），CSS 才有可淡入的起点', () => {
		render(<PageViewPane {...paneProps({shown: false})} />);
		expect(pane().className).toContain('opacity-0');
		expect(pane().className).not.toContain('opacity-100');
		expect(pane().getAttribute('class')).toContain('transition-');
	});

	it('帧满了且仍是当前页面才可见', () => {
		render(<PageViewPane {...paneProps({shown: true})} />);
		expect(pane().className).toContain('opacity-100');
	});

	it('让位中的旧页面（active=false）即使曾 shown 也立即转隐藏态', () => {
		render(<PageViewPane {...paneProps({active: false, shown: true})} />);
		expect(pane().className).toContain('opacity-0');
		expect(pane().getAttribute('aria-hidden')).toBe('true');
	});

	it('既非当前页面也不再挂载时整块消失', () => {
		render(<PageViewPane {...paneProps({active: false, mounted: false})} />);
		expect(screen.queryByTestId('pane-body')).toBeNull();
	});
});

describe('ChatPage 把 shown 接到每个页面视图（bug #5 的接线）', () => {
	it('三处 usePresence 都订了 shown', () => {
		for (const kind of ['usage', 'plugins', 'diagnostics']) {
			expect(chatPageSrc).toContain(`shown: ${kind}Shown`);
		}
	});

	it('三处 PageViewPane 都把 shown 传下去', () => {
		for (const kind of ['usage', 'plugins', 'diagnostics']) {
			expect(chatPageSrc).toContain(`shown={${kind}Shown}`);
		}
	});
});
