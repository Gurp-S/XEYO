/**
 * `useOverlayLock` 的判据面：锁只在 closed→open 那一拍捕获页面原值，
 * 关闭/卸载时交还它；多条浮层叠加时按后进先出还原。
 *
 * 另记一笔：我最初以为被替换掉的三份写法（`prev` 的捕获在不稳定的依赖表里）
 * 会漏锁，跑下面的等价性用例才发现 React 先 cleanup 再跑 effect 体，它们本来
 * 就是对的。所以这一刀是**纯去重**，不是修 bug。
 */
import {act, render} from '@testing-library/react';
import {useEffect, useState} from 'react';
import {describe, expect, it, vi} from 'vitest';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {useOverlayLock} from './useOverlayLock';

/** 新写法：内联 onClose 每次渲染换身份，锁也只捕获一次。 */
function Host({escId = 't', lockScroll = true}: {escId?: string; lockScroll?: boolean}) {
	const [open, setOpen] = useState(false);
	const [tick, setTick] = useState(0);
	useOverlayLock({open, escId, onEscape: () => setOpen(false), lockScroll});
	return (
		<>
			<button data-testid="open" onClick={() => setOpen(true)} />
			<button data-testid="rerender" onClick={() => setTick(t => t + 1)}>{tick}</button>
			<button data-testid="close" onClick={() => setOpen(false)} />
		</>
	);
}

/** 旧写法原样：不稳定的 onClose 进了依赖表。 */
function LegacyHost() {
	const [open, setOpen] = useState(false);
	const [tick, setTick] = useState(0);
	const onClose = () => setOpen(false);
	useEffect(() => {
		if (!open) {
			return;
		}
		const prev = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = prev;
		};
	}, [open, onClose]);
	return (
		<>
			<button data-testid="open" onClick={() => setOpen(true)} />
			<button data-testid="rerender" onClick={() => setTick(t => t + 1)}>{tick}</button>
			<button data-testid="close" onClick={() => setOpen(false)} />
		</>
	);
}

const click = (el: unknown) =>
	act(() => {
		(el as HTMLElement).click();
	});

describe('useOverlayLock', () => {
	it('打开锁滚动、关闭交还原值', () => {
		document.body.style.overflow = '';
		const {getByTestId} = render(<Host />);
		click(getByTestId('open'));
		expect(document.body.style.overflow).toBe('hidden');
		click(getByTestId('close'));
		expect(document.body.style.overflow).toBe('');
	});

	it('新写法：宿主每次渲染换 onClose 身份，关闭后仍交还原值', () => {
		document.body.style.overflow = '';
		const {getByTestId} = render(<Host />);
		click(getByTestId('open'));
		click(getByTestId('rerender'));
		click(getByTestId('rerender'));
		click(getByTestId('close'));
		expect(document.body.style.overflow).toBe('');
	});

	it('等价性：旧写法在同一序列下也交还原值（本条否证了我的一处推断）', () => {
		// 我先前判断"不稳定的 onClose 进依赖表 ⇒ prev 会记成 'hidden' ⇒ 关闭后
		// 永久锁死"。跑这条才发现：React 在依赖变化时先执行 cleanup 再执行
		// effect 体，prev 是在已解锁之后捕获的，所以旧写法不漏。
		// 这条留在这里的作用有两个：① 钉住 useOverlayLock 与旧形状等价；
		// ② 记下"推断要先跑一遍"这笔账。
		document.body.style.overflow = '';
		const {getByTestId} = render(<LegacyHost />);
		click(getByTestId('open'));
		expect(document.body.style.overflow).toBe('hidden');
		click(getByTestId('rerender'));
		expect(document.body.style.overflow).toBe('hidden');
		click(getByTestId('close'));
		expect(document.body.style.overflow).toBe('');
	});

	it('Esc 经 escStack：只有最上层响应，下层不动', () => {
		const lower = vi.fn();
		document.body.style.overflow = '';
		pushEscLayer('lower', lower);
		const {getByTestId, unmount} = render(<Host escId="upper" />);
		click(getByTestId('open'));
		act(() => {
			window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
		});
		expect(lower).not.toHaveBeenCalled();
		// 本层被 Esc 关掉后要立刻解锁（onEscape 走宿主状态，effect 随 open 收尾）
		expect(document.body.style.overflow).toBe('');
		unmount();
		popEscLayer('lower');
	});

	it('lockScroll=false 只借 Esc 配对，不碰页面滚动', () => {
		document.body.style.overflow = 'scroll';
		const {getByTestId, unmount} = render(<Host escId="nolock" lockScroll={false} />);
		click(getByTestId('open'));
		expect(document.body.style.overflow).toBe('scroll');
		unmount();
		expect(document.body.style.overflow).toBe('scroll');
	});
});
