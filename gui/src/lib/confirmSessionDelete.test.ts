import {afterEach, beforeAll, describe, expect, it} from 'vitest';
import sidebarSrc from '../components/Sidebar.tsx?raw';
import {confirmSessionDelete} from './confirmSessionDelete';

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
	for (const d of Array.from(document.querySelectorAll('dialog'))) {
		d.remove();
	}
});

function dialog(): HTMLDialogElement {
	const d = document.querySelector('dialog');
	if (!d) {
		throw new Error('未创建确认弹窗');
	}
	return d as HTMLDialogElement;
}

describe('confirmSessionDelete', () => {
	it('弹出 danger 确认，写出会话名与不可逆后果', async () => {
		const pending = confirmSessionDelete('重构消息列表');
		const d = dialog();
		expect(d.textContent).toContain('删除对话「重构消息列表」？');
		expect(d.textContent).toContain('无法恢复');
		const ok = d.querySelector('.xy-id-confirm');
		expect(ok?.classList.contains('xy-id-danger')).toBe(true);
		(ok as HTMLButtonElement).click();
		await expect(pending).resolves.toBe(true);
	});

	it('取消则返回 false（不执行删除）', async () => {
		const pending = confirmSessionDelete('测试会话');
		(dialog().querySelector('.xy-id-cancel') as HTMLButtonElement).click();
		await expect(pending).resolves.toBe(false);
	});

	it('无标题时回落「未命名」而不显示空占位', async () => {
		const pending = confirmSessionDelete(undefined);
		expect(dialog().textContent).toContain('删除对话「未命名」？');
		(dialog().querySelector('.xy-id-cancel') as HTMLButtonElement).click();
		await pending;
	});
});

describe('Sidebar 的两个删除入口都经过确认', () => {
	it('至少两处调用 confirmSessionDelete', () => {
		const hits = sidebarSrc.match(/confirmSessionDelete\(/g) ?? [];
		expect(hits.length).toBeGreaterThanOrEqual(2);
	});

	it('不再在无确认的情况下直接 await removeSession', () => {
		// 原缺陷形态：onRemoveSession 后紧跟 await removeSession(id)
		expect(sidebarSrc).not.toMatch(/onRemoveSession=\{(async )?id => \{\s*\n\s*const wasActive/);
	});
});
