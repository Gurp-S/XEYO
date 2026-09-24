/**
 * EvidenceChip 的复制反馈计时器（此前无任何覆盖）。
 *
 * 两条实测过的坏行为：
 * 1. 每次点击各留一个 setTimeout → 连点两次时，第一次那会在 1.2s 把勾撤掉，
 *    而用户是刚刚在第二次点击之后才看到勾的（反馈在眼前闪没）。
 * 2. 剪贴板写入是异步的 → 组件已卸载（切会话/换页）后回调仍然 setState、并在失败时
 *    弹一条"复制失败"，指向一个已经不存在的按钮。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, fireEvent, render, screen} from '@testing-library/react';
import {toast} from '@/lib/toast';
import {EvidenceChip} from './ui';
import type {DiagEvidenceRef} from '@/lib/api/diagnostics';

vi.mock('@/lib/toast', () => ({toast: {error: vi.fn(), success: vi.fn()}}));

const ref: DiagEvidenceRef = {
	source: 'audit',
	ref_id: 'evt-1',
	locator: 'turn=3',
	detail: '',
} as DiagEvidenceRef;

/** 用可访问名读"已复制"状态：图标本身是 aria-hidden，且 className 覆盖了 lucide 类名。 */
function isCopied() {
	return screen.queryByRole('button', {name: '已复制证据定位'}) !== null;
}

/**
 * 挂剪贴板。**必须**用 defineProperty：jsdom 的 `navigator.clipboard` 是原型上的
 * getter，`Object.assign(navigator, {...})` 会静默失败，于是四条用例全都悄悄走
 * execCommand 回退分支 —— 失败用例照样"通过"，成功用例永远不通过。
 */
function stubClipboard(writeText: (t: string) => Promise<void>) {
	Object.defineProperty(navigator, 'clipboard', {
		value: {writeText},
		configurable: true,
		writable: true,
	});
}

/**
 * 排干微任务/计时器，并**必须**包在 act 里：`copyText().then(setCopied)` 发生在
 * fireEvent 的 act 作用域之外，不包 act 则 React 的状态更新还没落到 DOM，
 * 断言就会读到旧图标（而只检查 mock 调用的用例照样"通过"——那种通过不算证据）。
 */
async function tick(ms = 0) {
	await act(async () => {
		await vi.advanceTimersByTimeAsync(ms);
	});
}

async function flush() {
	await tick(0);
}

function deferred() {
	let resolve!: () => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<void>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return {promise, resolve, reject};
}

beforeEach(() => {
	vi.useFakeTimers();
	vi.mocked(toast.error).mockClear();
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe('EvidenceChip', () => {
	it('复制成功后显示"已复制"勾，1.2 秒后自动收起', async () => {
		const writeText = vi.fn(async () => undefined);
		stubClipboard(writeText);
		render(<EvidenceChip e={ref} />);

		fireEvent.click(screen.getByRole('button'));
		await flush();
		expect(isCopied()).toBe(true);
		expect(writeText).toHaveBeenCalledTimes(1);

		await tick(1300);
		expect(isCopied()).toBe(false);
	});

	it('连点两次时，第一次的计时器不许把第二次的勾提前撤掉', async () => {
		stubClipboard(vi.fn(async () => undefined));
		render(<EvidenceChip e={ref} />);
		const btn = screen.getByRole('button');

		fireEvent.click(btn);
		await flush();
		await tick(600);
		fireEvent.click(btn); // 第二次点击在 t=600，勾应续到 t=1800
		await flush();

		await tick(1190); // t=1790：第一次的 1.2s 早已过，勾必须还在
		expect(isCopied()).toBe(true);

		await tick(20); // t=1800：第二次的续期到点
		expect(isCopied()).toBe(false);
	});

	it('卸载后：剪贴板失败也不给一个已经不存在的按钮弹提示', async () => {
		const gate = deferred();
		stubClipboard(
			vi.fn(() =>
				gate.promise.then(() => {
					throw new Error('clipboard blocked');
				}),
			),
		);
		const {unmount} = render(<EvidenceChip e={ref} />);

		fireEvent.click(screen.getByRole('button'));
		unmount();
		gate.resolve();
		await flush();
		await tick(2000);

		expect(toast.error).not.toHaveBeenCalled();
		// 卸载后连"成功"的反馈也不该再产生（组件已经不在，勾无意义）
		expect(isCopied()).toBe(false);
	});

	it('挂载状态下同样的失败必须弹提示（上一条的反证，防止它空跑）', async () => {
		const gate = deferred();
		stubClipboard(
			vi.fn(() =>
				gate.promise.then(() => {
					throw new Error('clipboard blocked');
				}),
			),
		);
		render(<EvidenceChip e={ref} />);

		fireEvent.click(screen.getByRole('button'));
		gate.resolve();
		await flush();

		expect(toast.error).toHaveBeenCalledTimes(1);
		expect(isCopied()).toBe(false);
	});
});
