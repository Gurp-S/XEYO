import {afterEach, beforeAll, describe, expect, it, vi} from 'vitest';
import {confirmDialog, promptDialog} from './inlineDialog';
import {cssDurationMs} from './motionDuration';

beforeAll(() => {
	// jsdom 未实现 <dialog> 的 showModal/close，补最小可用桩。
	HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
		this.setAttribute('open', '');
	};
	HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
		this.removeAttribute('open');
	};
});

afterEach(() => {
	vi.useRealTimers();
	for (const d of Array.from(document.querySelectorAll('dialog'))) {
		d.remove();
	}
});

function q<T extends Element>(sel: string): T {
	const el = document.querySelector(sel);
	if (!el) {
		throw new Error(`未找到 ${sel}`);
	}
	return el as T;
}

describe('A4 退出动画：关闭时先播过渡再移除，而非瞬消', () => {
	it('确认后弹窗仍在 DOM，且已挂 xy-id-closing', async () => {
		vi.useFakeTimers();
		const pending = confirmDialog({title: '删除？', confirmText: '删除', danger: true});
		const card = q<HTMLElement>('.xy-id-card');
		q<HTMLButtonElement>('.xy-id-confirm').click();

		// Promise 立即 resolve，调用方无需等待动画
		await expect(pending).resolves.toBe(true);

		// 但 DOM 还在，处于退出过渡态（修复前此处已被 dlg.remove() 瞬消）
		expect(card.classList.contains('xy-id-closing')).toBe(true);
		expect(document.querySelector('dialog')).not.toBeNull();
	});

	it('过渡时长走完后才真正移除', async () => {
		vi.useFakeTimers();
		const pending = confirmDialog({title: '删除？'});
		q<HTMLButtonElement>('.xy-id-confirm').click();
		await pending;

		expect(document.querySelector('dialog')).not.toBeNull();
		vi.advanceTimersByTime(cssDurationMs('fast') - 1);
		expect(document.querySelector('dialog')).not.toBeNull();
		vi.advanceTimersByTime(2);
		expect(document.querySelector('dialog')).toBeNull();
	});

	it('取消路径同样走退出过渡（进出对称）', async () => {
		vi.useFakeTimers();
		const pending = confirmDialog({title: '删除？'});
		const card = q<HTMLElement>('.xy-id-card');
		q<HTMLButtonElement>('.xy-id-cancel').click();
		await expect(pending).resolves.toBe(false);
		expect(card.classList.contains('xy-id-closing')).toBe(true);
		vi.advanceTimersByTime(cssDurationMs('fast') + 1);
		expect(document.querySelector('dialog')).toBeNull();
	});

	it('重复点击不会重复移除（settled 守卫生效）', async () => {
		vi.useFakeTimers();
		const pending = confirmDialog({title: '删除？'});
		const ok = q<HTMLButtonElement>('.xy-id-confirm');
		ok.click();
		ok.click();
		await pending;
		vi.advanceTimersByTime(cssDurationMs('fast') + 1);
		expect(document.querySelector('dialog')).toBeNull();
	});
});

describe('promptDialog 基础契约', () => {
	it('输入值经确认后返回', async () => {
		vi.useFakeTimers();
		const pending = promptDialog({title: '链接地址', initial: 'https://'});
		const input = q<HTMLInputElement>('.xy-id-input');
		input.value = 'https://example.com';
		q<HTMLButtonElement>('.xy-id-confirm').click();
		await expect(pending).resolves.toBe('https://example.com');
		vi.advanceTimersByTime(cssDurationMs('fast') + 1);
	});

	it('空白输入不确认，弹窗保持打开', async () => {
		vi.useFakeTimers();
		const pending = promptDialog({title: '链接地址', initial: '   '});
		q<HTMLButtonElement>('.xy-id-confirm').click();
		expect(document.querySelector('dialog')).not.toBeNull();
		q<HTMLButtonElement>('.xy-id-cancel').click();
		await expect(pending).resolves.toBeNull();
		vi.advanceTimersByTime(cssDurationMs('fast') + 1);
	});
});
