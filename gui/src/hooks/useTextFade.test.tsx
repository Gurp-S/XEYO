/**
 * useTextFade 的回归守卫。
 *
 * 复现的缺陷：侧栏的渐变淡出无条件挂在标题格上，把根本没溢出的名字（「本地工作区」）
 * 末字一起淡掉，看起来像被截了。现在遮罩只在真被裁时生效，标记由这个钩子打。
 *
 * 三条判据（穷举破坏方式）：
 * ① 裁了才打、不裁必须摘（改名后不能留旧标记）；
 * ② content-visibility 跳过的行（contentRect.width===0）不逼布局、不动标记；
 * ③ 没有 ResizeObserver 的环境（jsdom / 老内核）fail-open，不炸渲染。
 */
import {cleanup, render} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

type Entry = {target: Element; contentRect: {width: number}};

class FakeRO {
	targets = new Set<Element>();
	cb: (entries: Entry[]) => void;
	constructor(cb: (entries: Entry[]) => void) {
		this.cb = cb;
		instances.add(this);
	}
	observe(el: Element) {
		this.targets.add(el);
	}
	unobserve(el: Element) {
		this.targets.delete(el);
	}
	disconnect() {
		instances.delete(this);
	}
}

let instances = new Set<FakeRO>();
let useTextFade: <T extends HTMLElement>(dep: unknown) => {readonly current: T | null};

function Probe({title}: {title: string}) {
	const ref = useTextFade<HTMLSpanElement>(title);
	return <span ref={ref}>{title}</span>;
}

/** 真实 ResizeObserver 在 observe() 时自带一次回调，这里手动投递同一件事。 */
function resize(el: Element, contentWidth: number) {
	for (const ro of instances) ro.cb([{target: el, contentRect: {width: contentWidth}}]);
}

function setSizes(el: HTMLElement, scrollWidth: number, clientWidth: number) {
	Object.defineProperty(el, 'scrollWidth', {configurable: true, value: scrollWidth});
	Object.defineProperty(el, 'clientWidth', {configurable: true, value: clientWidth});
}

async function loadHook() {
	vi.resetModules();
	const m = await import('./useTextFade');
	useTextFade = m.useTextFade;
}

describe('useTextFade', () => {
	beforeEach(async () => {
		instances = new Set();
		vi.stubGlobal('ResizeObserver', FakeRO);
		await loadHook();
	});
	afterEach(() => {
		cleanup();
		vi.unstubAllGlobals();
	});

	it('只有真被裁才打 data-fade，不裁要摘掉', () => {
		const {container} = render(<Probe title="本地工作区" />);
		const el = container.querySelector('span') as HTMLElement;

		setSizes(el, 60, 198);
		resize(el, 198);
		expect(el.hasAttribute('data-fade')).toBe(false);

		setSizes(el, 320, 198);
		resize(el, 198);
		expect(el.hasAttribute('data-fade')).toBe(true);

		// 改名后放得下了：上一轮的标记必须摘掉，否则末字仍被淡
		setSizes(el, 60, 198);
		resize(el, 198);
		expect(el.hasAttribute('data-fade')).toBe(false);
	});

	it('未布局的行（content-visibility 跳过）不动标记', () => {
		const {container} = render(<Probe title="排查 WSC 高成本与命中率" />);
		const el = container.querySelector('span') as HTMLElement;
		setSizes(el, 320, 198);
		resize(el, 198);
		expect(el.hasAttribute('data-fade')).toBe(true);

		// 滚出视口：尺寸读出来是 0，此时不许强读布局、也不许清掉已知状态
		setSizes(el, 0, 0);
		resize(el, 0);
		expect(el.hasAttribute('data-fade')).toBe(true);
	});

	it('dep 变化会重新登记（改名后能再量一次）', () => {
		const {container, rerender} = render(<Probe title="甲" />);
		const el = container.querySelector('span') as HTMLElement;
		expect([...instances].some((ro) => ro.targets.has(el))).toBe(true);
		rerender(<Probe title="乙" />);
		expect([...instances].some((ro) => ro.targets.has(el))).toBe(true);
	});

	it('没有 ResizeObserver 的环境 fail-open，不炸渲染', async () => {
		vi.stubGlobal('ResizeObserver', undefined);
		await loadHook();
		const {container} = render(<Probe title="本地工作区" />);
		const el = container.querySelector('span') as HTMLElement;
		expect(el.textContent).toBe('本地工作区');
		expect(el.hasAttribute('data-fade')).toBe(false);
	});
});
