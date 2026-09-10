import {useEffect, useRef, type RefObject} from 'react';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';

/**
 * 浮层可达性基座：焦点陷阱 + Esc 关闭 + 关闭后焦点归还 + 背景 inert。
 *
 * 现状缺口（本项目实测）：全仓 `inert` 出现 0 次、无任何焦点陷阱实现。
 * 结果是无鼠标用户被困在弹层里、Tab 会穿到背景元素。
 *
 * 设计取舍：
 * - Esc 可选。缺省不接管——调用方若已有自己的 Esc 处理（如 SettingsModal 的
 *   capture + stopPropagation 语义），传 escId 会造成两个处理器同时开火。
 *   需要时传 `escId` + `onEscape`，复用既有 `escStack`（后进先出），
 *   多层浮层叠加时只有最上层响应。
 * - 背景隔离沿**祖先链**逐层施加：从浮层根向上直到 body，每层把「不在路径上」
 *   的兄弟节点标 inert。portal 形态（根是 body 直接子元素）下退化为只标 body
 *   的其余子节点；inline 渲染的全屏浮层也能正确隔离。路径上的节点永不标 inert，
 *   所以浮层自身不会失效。
 * - 关闭后仅在焦点仍留在浮层内（或已丢失到 body）时归还，避免抢走用户新点的目标。
 */

const FOCUSABLE_SELECTOR = [
	'a[href]',
	'button:not([disabled])',
	'input:not([disabled])',
	'select:not([disabled])',
	'textarea:not([disabled])',
	'[tabindex]:not([tabindex="-1"])',
].join(', ');

function focusablesIn(root: HTMLElement): HTMLElement[] {
	return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
		el => !el.hasAttribute('hidden') && el.getAttribute('aria-hidden') !== 'true',
	);
}

export type ModalA11yOptions = {
	open: boolean;
	/** 浮层最外层节点。 */
	rootRef: RefObject<HTMLElement | null>;
	/** escStack 层标识；与 onEscape 一起提供时才接管 Esc。 */
	escId?: string;
	onEscape?: () => void;
};

export function useModalA11y({open, rootRef, escId, onEscape}: ModalA11yOptions): void {
	// 回调走 ref，避免调用方未 memo 时每次渲染都重建 inert / 重推 Esc 层。
	const escRef = useRef(onEscape);
	escRef.current = onEscape;
	const takeEsc = Boolean(escId && onEscape);

	useEffect(() => {
		if (!open) {
			return;
		}
		const root = rootRef.current;
		if (!root) {
			return;
		}

		// 焦点归还目标：弹层打开前正在聚焦的元素。
		const restoreTo =
			document.activeElement instanceof HTMLElement ? document.activeElement : null;

		// 背景隔离：沿祖先链逐层标记，路径上的节点跳过。
		const inerted: HTMLElement[] = [];
		let node: HTMLElement | null = root;
		while (node && node !== document.body) {
			const parent: HTMLElement | null = node.parentElement;
			if (!parent) {
				break;
			}
			for (const sibling of Array.from(parent.children)) {
				if (sibling === node || sibling.contains(node)) {
					continue;
				}
				if (!(sibling instanceof HTMLElement) || sibling.hasAttribute('inert')) {
					continue;
				}
				sibling.setAttribute('inert', '');
				inerted.push(sibling);
			}
			node = parent;
		}

		if (takeEsc) {
			pushEscLayer(escId as string, () => escRef.current?.());
		}

		const onKeyDown = (e: KeyboardEvent) => {
			if (e.key !== 'Tab') {
				return;
			}
			const items = focusablesIn(root);
			if (items.length === 0) {
				e.preventDefault();
				return;
			}
			const first = items[0];
			const last = items[items.length - 1];
			const active = document.activeElement;
			if (!(active instanceof HTMLElement) || !root.contains(active)) {
				e.preventDefault();
				first.focus();
				return;
			}
			if (e.shiftKey && active === first) {
				e.preventDefault();
				last.focus();
			} else if (!e.shiftKey && active === last) {
				e.preventDefault();
				first.focus();
			}
		};
		// 挂在 document 捕获阶段而非浮层根：焦点一旦逃到背景（inert 不支持的
		// 环境、或程序性 focus），挂在浮层上的监听根本收不到 Tab，陷阱即失效。
		document.addEventListener('keydown', onKeyDown, true);

		// 打开后把焦点移进浮层——否则焦点仍停在触发按钮上，Tab 陷阱虽有
		// 但读屏焦点语义还在背景。
		if (!root.contains(document.activeElement)) {
			(focusablesIn(root)[0] ?? root).focus();
		}

		return () => {
			document.removeEventListener('keydown', onKeyDown, true);
			if (takeEsc) {
				popEscLayer(escId as string);
			}
			for (const el of inerted) {
				el.removeAttribute('inert');
			}
			const active = document.activeElement;
			const focusLeftOverlay =
				!active || active === document.body || root.contains(active);
			if (focusLeftOverlay && restoreTo?.isConnected) {
				restoreTo.focus();
			}
		};
	}, [open, rootRef, escId, takeEsc]);
}
