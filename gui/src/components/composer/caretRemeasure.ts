/**
 * 自绘光标重测失效源(caret remeasure)。
 *
 * 结构性根因:自绘光标的坐标是「某一帧的测量结果」,此前只在 value / caret /
 * 焦点变化或 textarea scroll 时重算。凡是「值没变、文本位置变了」的布局变化都
 * 没有信号:
 *   - textarea 自动高度动画(`transition-[height] duration-200`)期间逐帧重排;
 *   - 分栏拖拽 / 窗口缩放改变作曲卡宽度 → 换行点变化;
 *   - web font 迟到替换 → 字形度量变化(RO 看不见,因为容器框可能一点没动)。
 * 结果:光标停在旧坐标不动,直到下一次按键才"跳"回去(用户读感 = 错位 + 闪)。
 *
 * 这里把三类失效源合并成「每帧至多一次」的重测请求,由调用方用 snap 档重定位
 * (snap 不搅动呼吸节律与运动档,见 TypingCaret.placeCaret)。
 *
 * fail-open 契约:任何来源缺失、被拒或抛异常(jsdom 无 ResizeObserver、无
 * document.fonts、观察器构造失败)都只降级为「少一个信号」,绝不抛出、绝不
 * 让光标停摆;测量与显示始终可回退到原来的 value/caret/scroll 三路驱动。
 */

export interface CaretRemeasureEnv {
	/** 帧回调;缺省用 requestAnimationFrame,再缺省同步执行。 */
	requestFrame?: (cb: () => void) => number;
	cancelFrame?: (handle: number) => void;
	/** 订阅元素尺寸变化,返回解绑函数;不支持时返回 null。 */
	watchResize?: (el: Element, cb: () => void) => (() => void) | null;
	/** 订阅字体度量就绪/新增,返回解绑函数;不支持时返回 null。 */
	watchFonts?: (cb: () => void) => (() => void) | null;
	/** 订阅窗口尺寸变化,返回解绑函数;不支持时返回 null。 */
	watchWindowResize?: (cb: () => void) => (() => void) | null;
}

export interface CaretRemeasure {
	/** 绑定承载镜像与光标的容器(尺寸变化 = 文本重排)。换绑自动解旧。 */
	attach: (el: Element) => void;
	/** 请求一次重测(帧内幂等)。 */
	invalidate: () => void;
	/** 解绑全部来源并丢弃挂起的帧回调。 */
	dispose: () => void;
}

const defaultWatchResize = (
	el: Element,
	cb: () => void,
): (() => void) | null => {
	if (typeof ResizeObserver !== 'function') {
		return null;
	}
	try {
		const ro = new ResizeObserver(() => cb());
		ro.observe(el);
		return () => ro.disconnect();
	} catch {
		return null;
	}
};

const defaultWatchWindowResize = (cb: () => void): (() => void) | null => {
	if (typeof window === 'undefined') {
		return null;
	}
	try {
		window.addEventListener('resize', cb);
		return () => window.removeEventListener('resize', cb);
	} catch {
		return null;
	}
};

const defaultWatchFonts = (cb: () => void): (() => void) | null => {
	if (typeof document === 'undefined') {
		return null;
	}
	const fonts = (document as Document & {fonts?: FontFaceSet}).fonts;
	if (!fonts) {
		return null;
	}
	const unbind: (() => void)[] = [];
	try {
		fonts.addEventListener('loadingdone', cb);
		unbind.push(() => fonts.removeEventListener('loadingdone', cb));
	} catch {
		/* 只丢了"后续字体加载"这一路信号 */
	}
	try {
		/* ready 是首次字体集合确定的信号;迟到替换的字形重排由它兜一次。
		   解绑后仍可能 resolve,cb 侧自带 disposed 短路。 */
		void Promise.resolve(fonts.ready)
			.then(() => cb())
			.catch(() => {});
	} catch {
		/* 同上 */
	}
	if (unbind.length === 0) {
		return null;
	}
	return () => {
		for (const off of unbind) {
			off();
		}
	};
};

export function createCaretRemeasure(
	onInvalidate: () => void,
	env: CaretRemeasureEnv = {},
): CaretRemeasure {
	const requestFrame =
		env.requestFrame ??
		(typeof requestAnimationFrame === 'function'
			? (cb: () => void) => requestAnimationFrame(() => cb())
			: (cb: () => void) => {
					cb();
					return 0;
				});
	const cancelFrame = env.cancelFrame ?? (() => {});
	const watchResize = env.watchResize ?? defaultWatchResize;
	const watchFonts = env.watchFonts ?? defaultWatchFonts;
	const watchWindowResize = env.watchWindowResize ?? defaultWatchWindowResize;

	let disposed = false;
	/* pending 与 handle 分开记:同步帧回调(测试替身 / 无 rAF 环境)会在赋值
	   语句返回前就把 pending 清掉,单靠 handle 判重会永久卡死后续请求。 */
	let pending = false;
	let handle: number | null = null;
	let unbindTarget: (() => void) | null = null;
	let observerOff: (() => void) | null = null;

	const fire = () => {
		pending = false;
		handle = null;
		if (disposed) {
			return;
		}
		onInvalidate();
	};

	const schedule = () => {
		if (disposed || pending) {
			return;
		}
		pending = true;
		const h = requestFrame(fire);
		if (pending) {
			handle = h;
		}
	};

	const bindSources = (el: Element) => {
		observerOff = watchResize(el, schedule);
		const offWindow = watchWindowResize(schedule);
		const offFonts = watchFonts(schedule);
		unbindTarget = () => {
			observerOff?.();
			observerOff = null;
			offWindow?.();
			offFonts?.();
		};
	};

	return {
		attach(el: Element) {
			if (disposed) {
				return;
			}
			unbindTarget?.();
			unbindTarget = null;
			bindSources(el);
			/* 绑定即对齐一次:挂载前发生的重排(如 IME 组词期间覆盖层被卸载)
			   没有观察者,靠这一帧补上。 */
			schedule();
		},
		invalidate: schedule,
		dispose() {
			disposed = true;
			pending = false;
			unbindTarget?.();
			unbindTarget = null;
			if (handle !== null) {
				cancelFrame(handle);
				handle = null;
			}
		},
	};
}
