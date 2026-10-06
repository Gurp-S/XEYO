import {useEffect, useRef} from 'react';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';

/**
 * 遮罩期间锁住页面滚动 + 把 Esc 接进 escStack。
 *
 * 抽出原因：这段保存/恢复 `body.style.overflow` 的代码在 ImageReader、
 * MermaidBlock、PanelExpandOverlay 里各写了一遍，且都成对（漏一个 restore
 * 就永久锁死页面）。多浮层叠加时按后进先出还原：内层记下的是 'hidden'，
 * 关掉后交还给外层，不会把背景解锁。
 */
export function useOverlayLock({
	open,
	escId,
	onEscape,
	lockScroll = true,
}: {
	open: boolean;
	escId: string;
	onEscape?: () => void;
	/** 只借 Esc 配对、不锁滚动的宿主（如就地展开的抽屉）把这条关掉。 */
	lockScroll?: boolean;
}) {
	// 回调走 ref：调用方传内联箭头时不能让它进依赖表，否则每次渲染都
	// 重锁一次滚动（overflow 反复 hidden→'' 会造成可视跳动）。
	const escapeRef = useRef(onEscape);
	escapeRef.current = onEscape;
	const takeEsc = Boolean(onEscape);

	useEffect(() => {
		if (!open) {
			return;
		}
		const prev = lockScroll ? document.body.style.overflow : '';
		if (lockScroll) {
			document.body.style.overflow = 'hidden';
		}
		if (takeEsc) {
			pushEscLayer(escId, () => escapeRef.current?.());
		}
		return () => {
			if (lockScroll) {
				document.body.style.overflow = prev;
			}
			if (takeEsc) {
				popEscLayer(escId);
			}
		};
	}, [open, escId, lockScroll, takeEsc]);
}
