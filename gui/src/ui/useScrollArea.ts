import {useMemo, type Ref} from 'react';
import {cn} from '@/lib/utils';
import {useHoverScroll} from '@/hooks/useHoverScroll';

/**
 * 滚动区基座：把「全局滚动条皮肤要三点接线」收成人无法漏接的返回值。
 *
 * 为什么要有它：皮肤的显形由 `.xy-hover-scroll-on` / 宿主的 `.xy-hover-host-on`
 * 驱动，而这个类只有 `useHoverScroll` 的定时器会加。历史上 5 处只留了
 * `.xy-hover-scroll` 类、没接 hook —— 滑块底色是 transparent，于是那块区域
 * **等于没有滚动条**。这类漏接无法靠 review 挡住，所以把接线面收成一次 spread。
 *
 * 皮肤本体仍在 `styles/shell.css`（唯一真源），这里只负责让它生效。
 */
export type ScrollAreaOptions = {
	/** 悬停多久后显形滑块；默认沿用聊天列的 100ms。 */
	delayMs?: number;
	/**
	 * 边缘渐隐（mask）。聊天列开；历史上没挂过 fade 的面板要保持原样，
	 * 否则这一刀就从「修滚动条」变成「加渐隐」了。
	 */
	edgeFade?: boolean;
	edgeFadeTop?: boolean;
	edgeFadeTopSize?: number;
	/** 宿主另有命令式句柄时（虚拟列表、scrollTo 归位）一并回填。 */
	outerRef?: Ref<HTMLElement>;
	/**
	 * 关掉整条接线。用在「同一组件两种形态，只有其中一种用 hover 皮肤」的
	 * 宿主（如 PageShell 的宽版页面走常显皮肤），这样 props 可以无条件 spread，
	 * 不必在三行上各写一个三元。
	 */
	enabled?: boolean;
};

export function useScrollArea(options: ScrollAreaOptions = {}) {
	const {delayMs, edgeFade, edgeFadeTop, edgeFadeTopSize, outerRef, enabled = true} = options;
	const hover = useHoverScroll(delayMs, {edgeFade, edgeFadeTop, edgeFadeTopSize});
	const {scrollerRef, hostRef, onMouseEnter, onMouseLeave} = hover;

	return useMemo(() => {
		const handlers = {onMouseEnter, onMouseLeave};
		const withOuter = (
			bind: (el: HTMLElement | null) => void,
		): ((el: HTMLElement | null) => void) =>
			el => {
				bind(el);
				if (!outerRef) {
					return;
				}
				if (typeof outerRef === 'function') {
					outerRef(el);
				} else {
					(outerRef as {current: HTMLElement | null}).current = el;
				}
			};
		if (!enabled) {
			return {
				scrollerProps: {},
				hostProps: {},
				onlyHandlers: {},
				cx: (...extra: (string | false | null | undefined)[]) => cn(...extra),
			};
		}
		return {
			/**
			 * 挂在滚动元素本身：类与状态同节点，最常见的一种。
			 * 用法 `className={cx('overflow-y-auto')} {...scrollerProps}`。
			 */
			scrollerProps: {...handlers, ref: withOuter(scrollerRef)},
			/**
			 * 挂在**悬停区**上（滚动元素是它的后代时用这个）：宿主只负责判定
			 * 区域，穿透规则见 `styles/shell.css` 的宿主档。
			 */
			hostProps: {...handlers, ref: withOuter(hostRef)},
			/** 供宿主自己已经持有 ref 的场景（如共享 setBodyRef）。 */
			onlyHandlers: handlers,
			cx: (...extra: (string | false | null | undefined)[]) =>
				cn('xy-hover-scroll', ...extra),
		};
	}, [scrollerRef, hostRef, onMouseEnter, onMouseLeave, outerRef, enabled]);
}
