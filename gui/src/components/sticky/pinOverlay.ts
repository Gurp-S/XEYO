import type {ChatMessage} from '@/lib/types';
import {
	applyChipMaxHeight,
	isChipOverflowing,
	px,
	readBgDrawPos,
	setOverflowFlag,
	syncPromptClampOverflow,
} from './stickyGeometry';
import {
	PIN_CHIP_CLASS,
	PIN_TEXT_CLASS,
	STICKY_SELF_WALLPAPER,
	type PinView,
} from './stickyTypes';

export function pinMessageEditable(
	id: string,
	editable: Map<string, boolean>,
	messages: ChatMessage[],
): boolean {
	if (!editable.get(id)) {
		return false;
	}
	const msg = messages.find(m => m.id === id);
	return Boolean(
		msg && msg.source !== 'remote' && !msg.text.startsWith('[远程]'),
	);
}

export function clearPinOverlay(
	overlay: HTMLElement | null,
	pinNodes: Map<string, HTMLElement>,
): void {
	for (const node of pinNodes.values()) {
		node.remove();
	}
	pinNodes.clear();
	if (overlay) {
		overlay.setAttribute('aria-hidden', 'true');
	}
}

/** Imperative pin layer — stays in sync with clip-path (no React render lag). */
export function syncPinOverlay(
	overlay: HTMLElement | null,
	pinNodes: Map<string, HTMLElement>,
	pins: PinView[],
	retainPortalId: string | null,
	editable: Map<string, boolean>,
	messages: ChatMessage[],
	/** 流内 chip 查询：命中时整克隆（含 Markdown 渲染结果），pin 与流内像素一致。 */
	chipFor?: (id: string) => HTMLElement | null,
): void {
	if (!overlay) {
		return;
	}
	/* 自绘壁纸（阶段1）：pin 背景按“壁纸绘制原点 − 芯片窗口原点”内联对齐 L0 像素。
	   overlayRect/drawPos 每次 sync 读一次，不进 per-pin 测量。 */
	const selfWallpaper = STICKY_SELF_WALLPAPER;
	const overlayRect = selfWallpaper
		? overlay.getBoundingClientRect()
		: null;
	/* Bug 2：drawPos 必须从 overlay（AppShell 容器后代，继承 --xy-bg-draw-pos）读取；
	   从 documentElement 读恒为 0。 */
	const drawPos = selfWallpaper ? readBgDrawPos(overlay) : {x: 0, y: 0};
	const visible = pins.filter(pin => pin.id !== retainPortalId);
	const hasPortal = Boolean(retainPortalId && pinNodes.has(retainPortalId));
	overlay.setAttribute(
		'aria-hidden',
		visible.length === 0 && !hasPortal ? 'true' : 'false',
	);

	const nextIds = new Set(visible.map(pin => pin.id));
	for (const [id, node] of pinNodes) {
		if (!nextIds.has(id) && id !== retainPortalId) {
			node.remove();
			pinNodes.delete(id);
		}
	}

	for (const pin of visible) {
		let wrap = pinNodes.get(pin.id);
		if (!wrap) {
			wrap = document.createElement('div');
			wrap.dataset.pinId = pin.id;
			wrap.className = 'pointer-events-auto absolute';
			pinNodes.set(pin.id, wrap);
			overlay.appendChild(wrap);
		} else {
			/* Overlay may remount; re-home detached pins or the hole stays empty. */
			if (wrap.parentElement !== overlay) {
				overlay.appendChild(wrap);
			}
		}

		const pinText =
			pin.text ||
			messages.find(m => m.id === pin.id)?.text ||
			'';
		const liveChip = chipFor?.(pin.id) ?? null;
		if (liveChip) {
			/* 首选：整克隆流内 chip —— Markdown 渲染结果、媒体网格等与流内完全一致。
			   仅在文本变化或结构缺失时重建，避免每帧 cloneNode。 */
			const cloneStale =
				wrap.dataset.pinText !== pinText ||
				wrap.querySelector(':scope > .xy-user-prompt') === null;
			if (cloneStale) {
				wrap.dataset.pinText = pinText;
				const clone = liveChip.cloneNode(true) as HTMLElement;
				clone.removeAttribute('data-xy-prompt-chip');
				clone.classList.add('pointer-events-none');
				wrap.replaceChildren(clone);
			}
		} else {
			/* 回退：无流内 chip 可克隆时按原文重建纯文本 chip。 */
			if (!wrap.querySelector('.xy-prompt-clamp')) {
				const prevChip = wrap.firstElementChild;
				const prevText = wrap.querySelector<HTMLElement>('.xy-chat-text');
				if (prevChip && prevText && prevText.parentElement === prevChip) {
					const clamp = document.createElement('div');
					clamp.className = 'xy-prompt-clamp';
					prevChip.insertBefore(clamp, prevText);
					clamp.appendChild(prevText);
				} else {
					wrap.replaceChildren();
					const chip = document.createElement('div');
					chip.className = PIN_CHIP_CLASS;
					const clamp = document.createElement('div');
					clamp.className = 'xy-prompt-clamp';
					const textEl = document.createElement('div');
					textEl.className = PIN_TEXT_CLASS;
					clamp.appendChild(textEl);
					chip.appendChild(clamp);
					wrap.appendChild(chip);
				}
				wrap.dataset.pinText = pinText;
			}
			const textEl = wrap.querySelector<HTMLElement>('.xy-chat-text');
			if (textEl && textEl.textContent !== pinText) {
				textEl.textContent = pinText;
			}
		}

		const canEdit = pinMessageEditable(pin.id, editable, messages);
		wrap.classList.toggle('cursor-text', canEdit);
		if (canEdit) {
			wrap.setAttribute('role', 'button');
			wrap.setAttribute('tabindex', '0');
			wrap.setAttribute('aria-label', '编辑这条消息');
		} else {
			wrap.removeAttribute('role');
			wrap.removeAttribute('tabindex');
			wrap.removeAttribute('aria-label');
		}

		const clamp = wrap.querySelector<HTMLElement>('.xy-prompt-clamp');
		syncPromptClampOverflow(clamp);

		const chip = wrap.querySelector<HTMLElement>('.xy-user-prompt');
		/* pin/克隆与统一查看上限同高钳制（promptChipMaxPx，与 .xy-editing-bubble CSS
		   上限同源）。内容超高时打 data-xy-overflow 供 CSS 显示底部渐变淡出。 */
		applyChipMaxHeight(chip, true);
		setOverflowFlag(chip, isChipOverflowing(chip));
		if (selfWallpaper && overlayRect && chip) {
			/* 背景对齐：壁纸层原点 = 绘制原点 − 芯片窗口原点（pin.left/top 已是
			   overlay 坐标，overlay 原点即聊天视口原点）。 */
			const pos = `0 0, 0 0, ${px(drawPos.x - (overlayRect.left + pin.left))}px ${px(drawPos.y - (overlayRect.top + pin.top))}px`;
			if (chip.style.backgroundPosition !== pos) {
				chip.style.backgroundPosition = pos;
			}
		}

		const left = `${pin.left}px`;
		const top = `${pin.top}px`;
		const width = `${pin.width}px`;
		const height = `${Math.max(1, pin.height)}px`;
		if (wrap.style.left !== left) {
			wrap.style.left = left;
		}
		if (wrap.style.top !== top) {
			wrap.style.top = top;
		}
		if (wrap.style.width !== width) {
			wrap.style.width = width;
		}
		if (wrap.style.height !== height) {
			wrap.style.height = height;
		}
		if (wrap.style.maxHeight !== '') {
			wrap.style.maxHeight = '';
		}
	}
}
