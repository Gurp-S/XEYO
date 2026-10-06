import {useEffect, useRef} from 'react';
import type {RefObject} from 'react';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';

/**
 * 浮层的关闭配对：Esc（走 escStack，后进先出，多层只最上层响应）+ 外点关闭。
 *
 * 现状（实测）：全仓 15 个生产文件各写一遍这一块，且分成四种互不兼容的写法
 * —— document vs window、mousedown vs pointerdown、冒泡 vs 捕获、contains vs
 * getElementById。真正有动机的差异只有两列，所以只把它们做成参数：
 *
 * - `dismissOn:'pointerdown' + capture:true + arm:'nextTick'`：右键手势自身
 *   带一次按下，必须等这一拍过去再监听，否则刚开即关（ContextMenu 的历史做法）。
 * - `panelRef` / `panelId`：portal 形态的面板不在触发器子树里，`contains` 判
 *   不中，要单独放行。
 *
 * 其余按最常见的组合（document / mousedown / 冒泡）。
 *
 * 刻意不接管 Esc 的 window/document 冒泡监听：那些宿主在 escStack 之前还各挂了
 * 一份 `keydown`，而 escStack 在**捕获**阶段就 preventDefault + stopPropagation
 * 了 —— 本浮层是最上层时那份监听从不触发，属重复代码；本浮层不是最上层时它反而
 * 会越级关掉下层，正是 escStack 要消灭的行为。
 */
export type DismissArgs = {
	open: boolean;
	onClose: () => void;
	/** escStack 层标识：沿用宿主历史上的 id，不借重构改名。 */
	escId: string;
	/** 视为「内」的容器（通常是触发器所在包装层）。 */
	keepOpenRefs?: Array<RefObject<HTMLElement | null> | undefined>;
	/**
	 * 按属性选择器放行：一层浮层有**多个**面板时（右键菜单 + 子菜单都挂在
	 * body 上），逐个 ref 放行会漏，`closest('[data-xy-context-menu]')` 才是
	 * 那种宿主自己的形状。
	 */
	keepOpenSelector?: string;
	/** portal 形态下面板自身。 */
	panelRef?: RefObject<HTMLElement | null>;
	/** 面板按 id 挂在 body 时的放行方式（历史上用过这条的宿主保留）。 */
	panelId?: string;
	dismissOn?: 'mousedown' | 'pointerdown';
	capture?: boolean;
	arm?: 'immediate' | 'nextTick';
};

export function useDismiss({
	open,
	onClose,
	escId,
	keepOpenRefs = [],
	panelRef,
	panelId,
	dismissOn = 'mousedown',
	capture = false,
	arm = 'immediate',
	keepOpenSelector,
}: DismissArgs) {
	// 回调与放行目标都走 ref：宿主多数不 memo 这些数组，进依赖表会让监听
	// 每次渲染都卸了再装，外点关闭会出现空窗。
	const closeRef = useRef(onClose);
	closeRef.current = onClose;
	const refsRef = useRef(keepOpenRefs);
	refsRef.current = keepOpenRefs;
	const panelRefRef = useRef(panelRef);
	panelRefRef.current = panelRef;
	const panelIdRef = useRef(panelId);
	panelIdRef.current = panelId;
	const selectorRef = useRef(keepOpenSelector);
	selectorRef.current = keepOpenSelector;
	const takeEsc = Boolean(escId);

	useEffect(() => {
		if (!open) {
			return;
		}
		if (takeEsc) {
			pushEscLayer(escId, () => closeRef.current());
		}
		return () => {
			if (takeEsc) {
				popEscLayer(escId);
			}
		};
	}, [open, escId, takeEsc]);

	useEffect(() => {
		if (!open) {
			return;
		}
		const onDown = (event: Event) => {
			const t = event.target as Node | null;
			if (!t) {
				return;
			}
			for (const r of refsRef.current) {
				if (r?.current?.contains(t)) {
					return;
				}
			}
			if (
				selectorRef.current &&
				t instanceof Element &&
				t.closest(selectorRef.current)
			) {
				return;
			}
			if (panelRefRef.current?.current?.contains(t)) {
				return;
			}
			if (panelIdRef.current && document.getElementById(panelIdRef.current)?.contains(t)) {
				return;
			}
			closeRef.current();
		};
		const bind = () => {
			document.addEventListener(dismissOn, onDown, capture);
			return () => document.removeEventListener(dismissOn, onDown, capture);
		};
		if (arm === 'immediate') {
			return bind();
		}
		// nextTick：先等这一拍手势结束，再挂监听；否则刚打开就被同一次按下关掉。
		let off: (() => void) | null = null;
		const timer = window.setTimeout(() => {
			off = bind();
		}, 0);
		return () => {
			window.clearTimeout(timer);
			off?.();
		};
	}, [open, dismissOn, capture, arm]);
}
