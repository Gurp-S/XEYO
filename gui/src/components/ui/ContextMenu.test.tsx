import {cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {
	ContextMenuHost,
	closeContextMenu,
	openContextMenu,
} from './ContextMenu';
import {useContextMenuStore} from '@/stores/contextMenuStore';

afterEach(() => {
	cleanup();
	closeContextMenu();
});

describe('ContextMenuHost', () => {
	it('opens, runs action, and closes', async () => {
		const user = userEvent.setup();
		const onSelect = vi.fn();
		render(<ContextMenuHost />);

		openContextMenu({
			x: 40,
			y: 50,
			ariaLabel: '测试菜单',
			items: [
				{kind: 'action', id: 'copy', label: '复制', onSelect},
				{kind: 'sep'},
				{
					kind: 'action',
					id: 'del',
					label: '删除',
					danger: true,
					onSelect: vi.fn(),
				},
			],
		});

		expect(await screen.findByRole('menu', {name: '测试菜单'})).toBeTruthy();
		await user.click(screen.getByRole('menuitem', {name: '复制'}));
		expect(onSelect).toHaveBeenCalledTimes(1);
		await waitFor(() => {
			expect(useContextMenuStore.getState().menu).toBeNull();
		});
	});

	it('closes on Escape via esc stack', async () => {
		const user = userEvent.setup();
		render(<ContextMenuHost />);
		openContextMenu({
			x: 10,
			y: 10,
			items: [{kind: 'action', id: 'a', label: '动作', onSelect: vi.fn()}],
		});
		expect(await screen.findByRole('menu')).toBeTruthy();
		await user.keyboard('{Escape}');
		await waitFor(() => {
			expect(useContextMenuStore.getState().menu).toBeNull();
		});
	});
});
