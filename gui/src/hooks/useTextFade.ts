/**
 * 单行文字「真被裁了才淡出」的标记钩子。
 *
 * 为什么需要：渐变遮罩是按元素盒宽算的，只要挂上就会把落在淡出带里的最后一个字
 * 一起淡掉——而「本地工作区」这类根本没溢出的名字，末字正好落在带里，看起来像被截了。
 * 所以遮罩只在 scrollWidth > clientWidth 时生效，由这里打 data-fade 标记。
 *
 * 一个共享 ResizeObserver 服务侧栏所有标题格：行上有 content-visibility: auto，
 * 未布局的行在回调里按 contentRect.width === 0 跳过，不去逼它做布局。
 */
import {useLayoutEffect, useRef} from 'react';

let shared: ResizeObserver | null | undefined;

const mark = (el: HTMLElement) => {
	el.toggleAttribute('data-fade', el.scrollWidth - el.clientWidth > 1);
};

const ensureObserver = (): ResizeObserver | null => {
	if (shared === undefined) {
		shared =
			typeof ResizeObserver === 'function'
				? new ResizeObserver((entries) => {
						for (const entry of entries) {
							if (entry.contentRect.width === 0) continue;
							mark(entry.target as HTMLElement);
						}
					})
				: null;
	}
	return shared;
};

/**
 * dep 变化（改名、条数变化）时重新登记：observe 自带一次初始回调，
 * 量测与布局同帧，不需要在 React 提交阶段外强读布局。
 */
export function useTextFade<T extends HTMLElement>(dep: unknown) {
	const ref = useRef<T | null>(null);
	useLayoutEffect(() => {
		const el = ref.current;
		if (!el) return;
		const ro = ensureObserver();
		if (!ro) return;
		ro.unobserve(el);
		ro.observe(el);
		return () => {
			ro.unobserve(el);
		};
	}, [dep]);
	return ref;
}
