import {useCallback, useEffect, useRef} from 'react';

const SHOW_DELAY_MS = 100;
/** 边缘渐隐最大高度；随滚动量从 0 长到该值，近似高斯而不是硬切。 */
const FADE_PX = 40;
const FADE_EPS = 1;

function attachEdgeFade(
	el: HTMLElement,
	edgeFadeTop: boolean,
	topFadePx = FADE_PX,
): () => void {
	el.classList.add('xy-scroll-fade');
	let lastTop = -1;
	let lastBottom = -1;
	const sync = () => {
		const room = Math.max(0, el.clientHeight - 8);
			const topCap = Math.min(topFadePx, Math.floor(room / 2)); 
			const bottomCap = Math.min(FADE_PX, Math.floor(room / 2));
	      const top = edgeFadeTop ? Math.max(0, Math.min(topCap, el.scrollTop)) : 0;
			// 内容贴底（含亚像素误差）时强制关闭底部遮罩，避免最后几行被渐隐盖住。
			const atBottom =
				el.scrollTop + el.clientHeight >= el.scrollHeight - FADE_EPS;
			const bottom = atBottom
				? 0
				: Math.max(0, Math.min(bottomCap, el.scrollHeight - el.clientHeight - el.scrollTop));
		el.classList.toggle('is-fade-top', top > FADE_EPS);
		el.classList.toggle('is-fade-bottom', bottom > FADE_EPS);
		if (lastTop !== top) {
			lastTop = top;
			el.style.setProperty('--xy-fade-top', `${top}px`);
		}
		if (lastBottom !== bottom) {
			lastBottom = bottom;
			el.style.setProperty('--xy-fade-bottom', `${bottom}px`);
		}
	};
	el.addEventListener('scroll', sync, {passive: true});
	const ro =
		typeof ResizeObserver !== 'undefined' ? new ResizeObserver(sync) : null;
	ro?.observe(el);
	const watchKids = () => {
		for (const child of el.children) {
			if (child instanceof HTMLElement) {
				ro?.observe(child);
			}
		}
	};
	watchKids();
	const mo =
		typeof MutationObserver !== 'undefined'
			? new MutationObserver(() => {
					watchKids();
					sync();
				})
			: null;
	mo?.observe(el, {childList: true});
	sync();
	return () => {
		el.removeEventListener('scroll', sync);
		ro?.disconnect();
		mo?.disconnect();
		el.classList.remove('xy-scroll-fade', 'is-fade-top', 'is-fade-bottom');
		el.style.removeProperty('--xy-fade-top');
		el.style.removeProperty('--xy-fade-bottom');
	};
}

/** 鼠标进入区域 100ms 后显示滚动条，离开立即隐藏。不走 React state，避免整栏重绘。 */
export function useHoverScroll(
	delayMs = SHOW_DELAY_MS,
	options: {
		edgeFade?: boolean;
		edgeFadeTop?: boolean;
		edgeFadeTopSize?: number;
	} = {},
) {
  const edgeFade = options.edgeFade !== false;
	const edgeFadeTop = options.edgeFadeTop !== false;
	const edgeFadeTopSize = Math.max(0, options.edgeFadeTopSize ?? FADE_PX);
	const timer = useRef(0);
	const node = useRef<HTMLElement | null>(null);
	const fadeOff = useRef<(() => void) | null>(null);

	const scrollerRef = useCallback((el: HTMLElement | null) => {
		fadeOff.current?.();
		fadeOff.current = null;
		node.current = el;
		if (el && edgeFade) {
      fadeOff.current = attachEdgeFade(el, edgeFadeTop, edgeFadeTopSize);
		}
  }, [edgeFade, edgeFadeTop, edgeFadeTopSize]);

	useEffect(() => {
		return () => {
			if (timer.current) {
				window.clearTimeout(timer.current);
			}
			fadeOff.current?.();
			fadeOff.current = null;
		};
	}, []);

	return {
		scrollerRef,
		onMouseEnter() {
			if (timer.current) {
				window.clearTimeout(timer.current);
			}
			timer.current = window.setTimeout(() => {
				node.current?.classList.add('xy-hover-scroll-on');
				timer.current = 0;
			}, delayMs);
		},
		onMouseLeave() {
			if (timer.current) {
				window.clearTimeout(timer.current);
				timer.current = 0;
			}
			node.current?.classList.remove('xy-hover-scroll-on');
		},
	};
}
