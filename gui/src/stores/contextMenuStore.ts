import {create} from 'zustand';
import type {ReactNode} from 'react';

export type ContextMenuAction = {
	kind: 'action';
	id: string;
	label: string;
	disabled?: boolean;
	danger?: boolean;
	icon?: ReactNode;
	shortcut?: string;
	onSelect: () => void;
};

export type ContextMenuSubmenu = {
	kind: 'submenu';
	id: string;
	label: string;
	icon?: ReactNode;
	disabled?: boolean;
	items: ContextMenuItem[];
};

export type ContextMenuSep = {kind: 'sep'};

export type ContextMenuItem =
	| ContextMenuAction
	| ContextMenuSubmenu
	| ContextMenuSep;

export type ContextMenuState = {
	x: number;
	y: number;
	items: ContextMenuItem[];
	ariaLabel: string;
};

type Store = {
	menu: ContextMenuState | null;
	open: (args: {
		x: number;
		y: number;
		items: ContextMenuItem[];
		ariaLabel?: string;
	}) => void;
	close: () => void;
};

export const useContextMenuStore = create<Store>(set => ({
	menu: null,
	open({x, y, items, ariaLabel}) {
		set({
			menu: {
				x,
				y,
				items,
				ariaLabel: ariaLabel ?? '上下文菜单',
			},
		});
	},
	close() {
		set({menu: null});
	},
}));

export function openContextMenu(args: {
	x: number;
	y: number;
	items: ContextMenuItem[];
	ariaLabel?: string;
}): void {
	useContextMenuStore.getState().open(args);
}

export function closeContextMenu(): void {
	useContextMenuStore.getState().close();
}
