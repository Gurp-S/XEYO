import {afterEach, describe, expect, it, vi} from 'vitest';
import {joinWorkspacePath} from './workspaceOpen';

// 剪贴板/通知在 jsdom 里没有实体；toast 打桩避免真实 DOM 副作用，断言只盯剪贴板语义。
vi.mock('./toast', () => ({
	toast: {error: vi.fn(), info: vi.fn(), success: vi.fn(), warn: vi.fn()},
}));

describe('joinWorkspacePath', () => {
	it('joins relative paths with root separator style', () => {
		expect(joinWorkspacePath('D:\\proj', 'src/a.ts')).toBe('D:\\proj\\src/a.ts');
		expect(joinWorkspacePath('/home/u/p', 'src/a.ts')).toBe('/home/u/p/src/a.ts');
	});

	it('keeps absolute entry paths', () => {
		expect(joinWorkspacePath('/root', '/abs/file.ts')).toBe('/abs/file.ts');
		expect(joinWorkspacePath('D:\\root', 'D:\\other\\f.ts')).toBe('D:\\other\\f.ts');
	});

	it('returns entry when root empty', () => {
		expect(joinWorkspacePath('', 'rel.ts')).toBe('rel.ts');
	});
});

describe('contextMenus builders', () => {
	it('builds text field and file menus', async () => {
		const {textFieldMenuItems, filePathMenuItems, sessionMenuItems} =
			await import('./contextMenus');
		const ta = document.createElement('textarea');
		ta.value = 'hello';
		ta.setSelectionRange(0, 5);
		const textItems = textFieldMenuItems(ta);
		expect(textItems.some(i => i.kind === 'action' && i.id === 'copy')).toBe(
			true,
		);
		expect(textItems.some(i => i.kind === 'action' && i.id === 'paste')).toBe(
			true,
		);

		const fileItems = filePathMenuItems({
			entryPath: 'a.ts',
			entryName: 'a.ts',
			absolutePath: '/tmp/a.ts',
			kind: 'file',
			onOpen: () => undefined,
		});
		expect(fileItems.some(i => i.kind === 'action' && i.id === 'reveal')).toBe(
			true,
		);
		expect(fileItems.some(i => i.kind === 'action' && i.id === 'copy-rel')).toBe(
			true,
		);

		const sess = sessionMenuItems({
			sessionId: 's1',
			title: 't',
			onDelete: () => undefined,
		});
		expect(sess.some(i => i.kind === 'action' && i.id === 'delete')).toBe(true);
	});
});

describe('剪切的事务性：复制失败不许删选区', () => {
	const stubClipboardWrite = (fn: (() => Promise<void>) | null) => {
		Object.defineProperty(navigator, 'clipboard', {
			configurable: true,
			value: fn === null ? undefined : {writeText: fn},
		});
	};
	afterEach(() => {
		Object.defineProperty(navigator, 'clipboard', {
			configurable: true,
			value: undefined,
		});
	});

	it('复制失败：选区别动（不许剪贴板没拿到字、输入框里的字却没了）', async () => {
		const {copyTextToClipboard} = await import('./workspaceOpen');
		const {textFieldMenuItems} = await import('./contextMenus');
		// 剪贴板 API 拒绝 + jsdom 无 execCommand 回退 ⇒ 复制必失败。
		stubClipboardWrite(async () => {
			throw new Error('denied');
		});
		const ta = document.createElement('textarea');
		document.body.appendChild(ta);
		ta.value = 'hello';
		ta.setSelectionRange(0, 5);

		const cut = textFieldMenuItems(ta).find(
			i => i.kind === 'action' && i.id === 'cut',
		);
		if (!cut || cut.kind !== 'action') {
			throw new Error('未找到剪切项');
		}
		cut.onSelect();
		await new Promise(resolve => setTimeout(resolve, 0));
		// 先钉症状：复制失败时输入框里的字必须还在。
		expect(ta.value).toBe('hello');
		// 再钉根因链路：复制函数的成败返回值必须真实（成功才允许后续删除）。
		await expect(copyTextToClipboard('hello')).resolves.toBe(false);
		ta.remove();
	});

	it('复制成功：剪切照常清空选区', async () => {
		const {textFieldMenuItems} = await import('./contextMenus');
		stubClipboardWrite(async () => undefined);
		const ta = document.createElement('textarea');
		document.body.appendChild(ta);
		ta.value = 'hello';
		ta.setSelectionRange(0, 5);

		const cut = textFieldMenuItems(ta).find(
			i => i.kind === 'action' && i.id === 'cut',
		);
		if (!cut || cut.kind !== 'action') {
			throw new Error('未找到剪切项');
		}
		cut.onSelect();
		await new Promise(resolve => setTimeout(resolve, 0));
		expect(ta.value).toBe('');
		ta.remove();
	});
});
