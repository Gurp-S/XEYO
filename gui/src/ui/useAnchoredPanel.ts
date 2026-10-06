import {useLayoutEffect, useRef, useState} from 'react';
import type {CSSProperties, RefObject} from 'react';

/** 视口尺寸：place() 用它做翻转与夹取，避免每帧读 window。 */
export type Viewport = {width: number; height: number};

/** 由锚点矩形与视口算出面板定位；返回的 style 原样落到面板上。 */
export type PlaceFn = (
	anchor: DOMRect,
	vp: Viewport,
) => CSSProperties;

/**
 * portal 浮层的定位回路：测量锚点 → place() → 跟随 resize/scroll 重算。
 *
 * 为什么只收回路、不收公式：现有四份 portal 定位（ModelPicker /
 * WorkspaceAddMenu / ReasoningLevelsSelect / SessionPicker）的**监听与重算**
 * 逐字相同，**翻转判据**却各有一套（按剩余空间、按估高、按最小宽），这些差异
 * 是各自历史上调出来的。把公式强行并一就是改几何 —— 所以公式留在宿主，
 * 回路只此一份。
 *
 * 只在 open 时挂监听：关闭态不订阅 scroll（capture 阶段的 scroll 监听在流式期
 * 是每帧成本）。
 */
export function useAnchoredPanel({
	open,
	anchorRef,
	place,
	revision,
}: {
	open: boolean;
	anchorRef: RefObject<HTMLElement | null>;
	place: PlaceFn;
	/**
	 * 内容变化时要重新测量：面板自身尺寸参与翻转判据的宿主（WorkspaceAddMenu
	 * 读自己的 offsetWidth/Height），换视图或换列表长度后旧位置就错了。
	 */
	revision?: unknown;
}) {
	const placeRef = useRef(place);
	placeRef.current = place;
	const [style, setStyle] = useState<CSSProperties | null>(null);

	useLayoutEffect(() => {
		if (!open) {
			setStyle(null);
			return;
		}
		const update = () => {
			const anchor = anchorRef.current;
			if (!anchor) {
				return;
			}
			setStyle(
				placeRef.current(anchor.getBoundingClientRect(), {
					width: window.innerWidth,
					height: window.innerHeight,
				}),
			);
		};
		update();
		window.addEventListener('resize', update);
		window.addEventListener('scroll', update, true);
		return () => {
			window.removeEventListener('resize', update);
			window.removeEventListener('scroll', update, true);
		};
	}, [open, anchorRef, revision]);

	return style;
}
