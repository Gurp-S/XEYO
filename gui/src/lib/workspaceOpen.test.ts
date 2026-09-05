import {describe, expect, it} from 'vitest';
import {joinWorkspacePath} from './workspaceOpen';

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
