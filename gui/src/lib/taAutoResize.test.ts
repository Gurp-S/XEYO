import {describe, expect, it, vi} from 'vitest';
import {createTaAutoResize} from './taAutoResize';

/** rAF/布局环境桩:scrollHeight 按可变 contentPx 模拟,height 可读写。 */
function mountTa(contentPx: number) {
	const state = { content: contentPx };
	const el = {
		style: {} as Record<string, string>,
	} as unknown as HTMLTextAreaElement & {__state: {content: number}};
	Object.defineProperty(el, '__state', {value: state});
	Object.defineProperty(el, 'scrollHeight', {
		get() {
			// height:auto 时测得内容高度;显式高度时通常等于高度(简化桩)
			const h = el.style.height;
			return !h || h === 'auto' ? state.content : parseFloat(h);
		},
	});
	return el;
}

function rafSpy() {
	const cbs: FrameRequestCallback[] = [];
	vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
		cbs.push(cb);
		return cbs.length;
	});
	vi.stubGlobal('cancelAnimationFrame', () => {});
	return {
		flush() {
			const pending = cbs.splice(0);
			for (const cb of pending) cb(performance.now());
		},
	};
}

describe('taAutoResize', () => {
	it('高度夹在 min/max 之间并在 rAF 帧落盘', () => {
		const flusher = rafSpy();
		const r = createTaAutoResize({minPx: 36, maxPx: 120, isExpanded: () => false});
		const el = mountTa(60);
		r.schedule(el);
		expect(el.style.height).toBeUndefined(); // 关键路径上未写,延迟到帧
		flusher.flush();
		expect(el.style.height).toBe('60px');
		expect(el.style.overflowY).toBe('hidden');

		el.__state.content = 9999;
		r.schedule(el);
		flusher.flush();
		expect(el.style.height).toBe('120px');
		expect(el.style.overflowY).toBe('auto');

		el.__state.content = 1;
		r.schedule(el);
		flusher.flush();
		expect(el.style.height).toBe('36px');
		r.cancel();
	});

	it('同帧多次 schedule 只测一次;rAF 未 flush 前不写样式', () => {
		const flusher = rafSpy();
		const r = createTaAutoResize({minPx: 36, maxPx: 120, isExpanded: () => false});
		const el = mountTa(80);
		r.schedule(el);
		r.schedule(el);
		r.schedule(el);
		expect(el.style.height).toBeUndefined();
		flusher.flush();
		expect(el.style.height).toBe('80px');
		r.cancel();
	});

	it('写保护:测量高度不变时不重写 style(避免每键样式失效)', () => {
		const flusher = rafSpy();
		const r = createTaAutoResize({minPx: 36, maxPx: 120, isExpanded: () => false});
		const el = mountTa(60);
		r.schedule(el);
		flusher.flush();
		expect(el.style.height).toBe('60px');
		// 内容高度不变,再次调度:height/overflow 不被重写
		const h = el.style.height;
		const o = el.style.overflowY;
		r.schedule(el);
		flusher.flush();
		expect(el.style.height).toBe(h);
		expect(el.style.overflowY).toBe(o);
		r.cancel();
	});

	it('展开态不干预样式(调用方全权接管)', () => {
		const flusher = rafSpy();
		let expanded = true;
		const r = createTaAutoResize({minPx: 36, maxPx: 120, isExpanded: () => expanded});
		const el = mountTa(300);
		r.schedule(el);
		flusher.flush();
		expect(el.style.height).toBeUndefined();
		expanded = false;
		r.schedule(el);
		flusher.flush();
		expect(el.style.height).toBe('120px'); // 300 → 夹到 max
		r.cancel();
	});

	it('capped 边沿通知:onCapped 只在跨越阈值时变化', () => {
		const flusher = rafSpy();
		const seen: boolean[] = [];
		const r = createTaAutoResize({
			minPx: 36,
			maxPx: 120,
			isExpanded: () => false,
			onCapped: c => seen.push(c),
		});
		const el = mountTa(60);
		r.schedule(el);
		flusher.flush(); // false
		r.schedule(el);
		flusher.flush(); // 仍 false
		const el2 = mountTa(130);
		r.schedule(el2);
		flusher.flush(); // true
		expect(seen).toEqual([false, true]);
		r.cancel();
	});
});
