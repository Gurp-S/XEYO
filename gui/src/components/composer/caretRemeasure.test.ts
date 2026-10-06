import {describe, expect, it, vi} from 'vitest';
import {createCaretRemeasure, type CaretRemeasureEnv} from './caretRemeasure';

/** 可手动推进的帧调度器：把「每帧至多一次」变成可断言的时序。 */
const makeFrames = () => {
	const queue = new Map<number, () => void>();
	let next = 1;
	return {
		requestFrame: (cb: () => void) => {
			const h = next++;
			queue.set(h, cb);
			return h;
		},
		cancelFrame: (h: number) => {
			queue.delete(h);
		},
		flush: () => {
			const items = [...queue.values()];
			queue.clear();
			for (const cb of items) {
				cb();
			}
		},
		pending: () => queue.size,
	};
};

/** 可手动触发的来源替身：记录解绑次数。watch = 元素尺寸源(2 参)，watchPlain = 单参来源(字体/窗口)。 */
const makeSource = () => {
	let cb: (() => void) | null = null;
	let unbound = 0;
	const bind = (next: () => void) => {
		cb = next;
		return () => {
			unbound++;
			cb = null;
		};
	};
	return {
		watch: (_el: Element, next: () => void) => bind(next),
		watchPlain: (next: () => void) => bind(next),
		fire: () => cb?.(),
		unboundCount: () => unbound,
	};
};

const envWith = (
	frames: ReturnType<typeof makeFrames>,
	over: Partial<CaretRemeasureEnv> = {},
): CaretRemeasureEnv => ({
	requestFrame: frames.requestFrame,
	cancelFrame: frames.cancelFrame,
	watchFonts: () => null,
	watchWindowResize: () => null,
	...over,
});

describe('createCaretRemeasure', () => {
	it('同帧内多次失效只重测一次，且不丢后续请求', () => {
		const frames = makeFrames();
		const onInvalidate = vi.fn();
		const resize = makeSource();
		const r = createCaretRemeasure(onInvalidate, envWith(frames, {watchResize: resize.watch}));

		r.attach(document.createElement('div'));
		/* attach 只调度，不立即测量（测量要等布局落定） */
		expect(onInvalidate).not.toHaveBeenCalled();

		r.invalidate();
		resize.fire();
		resize.fire();
		expect(frames.pending()).toBe(1);

		frames.flush();
		expect(onInvalidate).toHaveBeenCalledTimes(1);

		/* 帧跑完之后必须还能再调度（同步帧回调下的"永久 pending"陷阱） */
		r.invalidate();
		expect(frames.pending()).toBe(1);
		frames.flush();
		expect(onInvalidate).toHaveBeenCalledTimes(2);
	});

	it('帧回调同步执行时不会卡死后续请求', () => {
		const onInvalidate = vi.fn();
		const r = createCaretRemeasure(onInvalidate, {
			requestFrame: cb => {
				cb();
				return 1;
			},
			watchResize: () => null,
			watchFonts: () => null,
			watchWindowResize: () => null,
		});
		r.attach(document.createElement('div'));
		expect(onInvalidate).toHaveBeenCalledTimes(1);
		r.invalidate();
		expect(onInvalidate).toHaveBeenCalledTimes(2);
	});

	it('窗口 resize 与字体就绪都触发重测', () => {
		const frames = makeFrames();
		const onInvalidate = vi.fn();
		const fonts = makeSource();
		const win = makeSource();
		const r = createCaretRemeasure(
			onInvalidate,
			envWith(frames, {
				watchResize: () => null,
				watchFonts: fonts.watchPlain,
				watchWindowResize: win.watchPlain,
			}),
		);
		r.attach(document.createElement('div'));
		frames.flush();
		expect(onInvalidate).toHaveBeenCalledTimes(1);

		fonts.fire();
		frames.flush();
		expect(onInvalidate).toHaveBeenCalledTimes(2);

		win.fire();
		frames.flush();
		expect(onInvalidate).toHaveBeenCalledTimes(3);
	});

	it('dispose 解绑全部来源、取消挂起帧，且之后不再回调', () => {
		const frames = makeFrames();
		const onInvalidate = vi.fn();
		const resize = makeSource();
		const fonts = makeSource();
		const win = makeSource();
		const r = createCaretRemeasure(
			onInvalidate,
			envWith(frames, {
				watchResize: resize.watch,
				watchFonts: fonts.watchPlain,
				watchWindowResize: win.watchPlain,
			}),
		);
		r.attach(document.createElement('div'));
		r.dispose();

		expect(frames.pending()).toBe(0);
		expect(resize.unboundCount()).toBe(1);
		resize.fire();
		fonts.fire();
		win.fire();
		frames.flush();
		expect(onInvalidate).not.toHaveBeenCalled();
	});

	it('换绑元素时解掉旧来源', () => {
		const frames = makeFrames();
		const resize = makeSource();
		const r = createCaretRemeasure(vi.fn(), envWith(frames, {watchResize: resize.watch}));
		r.attach(document.createElement('div'));
		r.attach(document.createElement('div'));
		expect(resize.unboundCount()).toBe(1);
	});

	it('fail-open：来源全部缺失时也能重测，且绝不抛', () => {
		const frames = makeFrames();
		const onInvalidate = vi.fn();
		const r = createCaretRemeasure(
			onInvalidate,
			envWith(frames, {watchResize: () => null}),
		);
		expect(() => r.attach(document.createElement('div'))).not.toThrow();
		frames.flush();
		expect(onInvalidate).toHaveBeenCalledTimes(1);
	});

	it('fail-open：jsdom 下默认来源（无 ResizeObserver / 无 document.fonts）不抛', () => {
		/* jsdom 观察器构造会直接抛；默认实现必须自行降级为"少一个信号"。
		   rAF 用 setup.ts 的同步替身，flush 即测量。 */
		const onInvalidate = vi.fn();
		const r = createCaretRemeasure(onInvalidate);
		expect(() => r.attach(document.createElement('div'))).not.toThrow();
		expect(() => r.invalidate()).not.toThrow();
		expect(onInvalidate).toHaveBeenCalled();
		r.dispose();
	});

	it('默认实现订阅真实 window resize', () => {
		const frames = makeFrames();
		const onInvalidate = vi.fn();
		/* 只注入帧调度与尺寸/字体替身：watchWindowResize 留空 → 走默认真实监听 */
		const r = createCaretRemeasure(onInvalidate, {
			requestFrame: frames.requestFrame,
			cancelFrame: frames.cancelFrame,
			watchResize: () => null,
			watchFonts: () => null,
		});
		r.attach(document.createElement('div'));
		frames.flush();
		const before = onInvalidate.mock.calls.length;

		window.dispatchEvent(new Event('resize'));
		frames.flush();
		expect(onInvalidate.mock.calls.length).toBe(before + 1);

		r.dispose();
		window.dispatchEvent(new Event('resize'));
		frames.flush();
		expect(onInvalidate.mock.calls.length).toBe(before + 1);
	});
});
