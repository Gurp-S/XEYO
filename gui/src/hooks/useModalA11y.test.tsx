import {act, render} from '@testing-library/react';
import {useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {describe, expect, it, vi} from 'vitest';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {useModalA11y} from './useModalA11y';

function Harness({onEscape}: {onEscape: () => void}) {
	const [open, setOpen] = useState(false);
	const rootRef = useRef<HTMLDivElement>(null);
	useModalA11y({open, rootRef, escId: 'test-modal', onEscape});
	return (
		<>
			<button data-testid="opener" onClick={() => setOpen(true)}>
				open
			</button>
			<button data-testid="closer" onClick={() => setOpen(false)}>
				close
			</button>
			{open
				? createPortal(
						<div ref={rootRef} data-testid="overlay">
							<button data-testid="first">1</button>
							<button data-testid="last">2</button>
						</div>,
						document.body,
					)
				: null}
		</>
	);
}

function q(testid: string): HTMLElement {
	const el = document.querySelector(`[data-testid="${testid}"]`);
	if (!el) {
		throw new Error(`未找到 ${testid}`);
	}
	return el as HTMLElement;
}

function pressEscape() {
	act(() => {
		window.dispatchEvent(
			new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}),
		);
	});
}

function pressTab(target: Element, shiftKey = false) {
	act(() => {
		target.dispatchEvent(
			new KeyboardEvent('keydown', {key: 'Tab', shiftKey, bubbles: true, cancelable: true}),
		);
	});
}

/** 打开浮层并返回容器（容器即「背景」）。 */
function openModal(onEscape = () => {}) {
	const view = render(<Harness onEscape={onEscape} />);
	const opener = q('opener');
	opener.focus();
	act(() => {
		opener.click();
	});
	return {view, opener};
}

describe('useModalA11y 背景隔离（inert）', () => {
	it('打开时给浮层之外的 body 直接子元素加 inert', () => {
		openModal();
		const overlay = q('overlay');
		expect(overlay.hasAttribute('inert')).toBe(false);
		const background = Array.from(document.body.children).filter(c => c !== overlay);
		expect(background.length).toBeGreaterThan(0);
		for (const bg of background) {
			expect(bg.hasAttribute('inert')).toBe(true);
		}
	});

	it('关闭后移除 inert（不残留）', () => {
		openModal();
		act(() => {
			q('closer').click();
		});
		expect(document.querySelector('[data-testid="overlay"]')).toBeNull();
		for (const child of Array.from(document.body.children)) {
			expect(child.hasAttribute('inert')).toBe(false);
		}
	});
});

describe('useModalA11y Esc 关闭', () => {
	it('Esc 触发 onEscape 回调', () => {
		const onEscape = vi.fn();
		openModal(onEscape);
		pressEscape();
		expect(onEscape).toHaveBeenCalledTimes(1);
	});

	it('未打开时 Esc 不触发（不占用 escStack 层）', () => {
		const onEscape = vi.fn();
		render(<Harness onEscape={onEscape} />);
		pressEscape();
		expect(onEscape).not.toHaveBeenCalled();
	});
});

describe('useModalA11y 焦点陷阱', () => {
	it('在末元素上 Tab 回卷到首元素', () => {
		openModal();
		const first = q('first');
		const last = q('last');
		last.focus();
		pressTab(last);
		expect(document.activeElement).toBe(first);
	});

	it('在首元素上 Shift+Tab 回卷到末元素', () => {
		openModal();
		const first = q('first');
		const last = q('last');
		first.focus();
		pressTab(first, true);
		expect(document.activeElement).toBe(last);
	});

	it('焦点意外落到浮层外时拉回首个可聚焦元素', () => {
		openModal();
		const opener = q('opener');
		opener.focus();
		const first = q('first');
		pressTab(opener);
		expect(document.activeElement).toBe(first);
	});
});

describe('useModalA11y 焦点归还', () => {
	it('关闭后焦点回到打开前的元素', () => {
		const {opener} = openModal();
		act(() => {
			q('closer').click();
		});
		expect(document.activeElement).toBe(opener);
	});
});

/** inline 形态：浮层不 portal，而是嵌在应用树深处（SettingsModal / RemoteQrPanel 即此形态）。 */
function InlineHarness({open}: {open: boolean}) {
	const rootRef = useRef<HTMLDivElement>(null);
	useModalA11y({open, rootRef});
	return (
		<div data-testid="app-root">
			<div data-testid="background-sibling">背景</div>
			<div>
				<div data-testid="deep-branch">
					{open ? (
						<div ref={rootRef} data-testid="inline-overlay">
							<button data-testid="inline-btn">确定</button>
						</div>
					) : null}
				</div>
			</div>
		</div>
	);
}

describe('useModalA11y 背景隔离（inline 祖先链）', () => {
	it('逐层标记不在路径上的兄弟节点，且浮层自身与其祖先不被标记', () => {
		const {rerender} = render(<InlineHarness open={false} />);
		rerender(<InlineHarness open />);

		// 路径上的节点永不 inert（否则浮层会失去交互）
		expect(q('inline-overlay').hasAttribute('inert')).toBe(false);
		expect(q('deep-branch').hasAttribute('inert')).toBe(false);
		expect(q('app-root').hasAttribute('inert')).toBe(false);
		expect(q('inline-btn').hasAttribute('inert')).toBe(false);
		// 路径外的兄弟被隔离
		expect(q('background-sibling').hasAttribute('inert')).toBe(true);

		rerender(<InlineHarness open={false} />);
		expect(q('background-sibling').hasAttribute('inert')).toBe(false);
	});
});

describe('useModalA11y Esc 可选', () => {
	it('未提供 escId 时不占 escStack 层，最上层仍是调用方自己的层', () => {
		// 先压一个哨兵层。若基座在未提供 escId 时仍推层，它就会顶掉哨兵，
		// Esc 便不再命中哨兵——这正是要防止的「两个处理器同时开火」。
		const sentinel = vi.fn();
		pushEscLayer('sentinel', sentinel);
		try {
			function NoEsc() {
				const r = useRef<HTMLDivElement>(null);
				useModalA11y({open: true, rootRef: r});
				return (
					<div ref={r}>
						<button>确定</button>
					</div>
				);
			}
			render(<NoEsc />);
			pressEscape();
			expect(sentinel).toHaveBeenCalledTimes(1);
		} finally {
			popEscLayer('sentinel');
		}
	});
});
