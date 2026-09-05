import {
	useCallback,
	useEffect,
	useId,
	useLayoutEffect,
	useRef,
	useState,
	type KeyboardEvent as ReactKeyboardEvent,
	type MouseEvent as ReactMouseEvent,
	type ReactNode,
} from 'react';
import {createPortal} from 'react-dom';
import {ChevronRight} from 'lucide-react';
import {cn} from '@/lib/utils';
import {MenuSeparator} from './MenuSeparator';
import {pushEscLayer, popEscLayer} from '@/lib/escStack';
import {
	closeContextMenu,
	openContextMenu,
	useContextMenuStore,
	type ContextMenuItem,
	type ContextMenuAction,
	type ContextMenuSubmenu,
} from '@/stores/contextMenuStore';

export type {ContextMenuItem, ContextMenuAction, ContextMenuSubmenu};
export {openContextMenu, closeContextMenu};

const MENU_PAD = 6;
const MENU_MIN_W = 168;
const MENU_ATTR = 'data-xy-context-menu';

function clampPos(
	x: number,
	y: number,
	width: number,
	height: number,
): {left: number; top: number} {
	const maxLeft = Math.max(MENU_PAD, window.innerWidth - width - MENU_PAD);
	const maxTop = Math.max(MENU_PAD, window.innerHeight - height - MENU_PAD);
	return {
		left: Math.min(Math.max(MENU_PAD, x), maxLeft),
		top: Math.min(Math.max(MENU_PAD, y), maxTop),
	};
}

function actionableItems(
	items: ContextMenuItem[],
): Array<ContextMenuAction | ContextMenuSubmenu> {
	return items.filter(
		(it): it is ContextMenuAction | ContextMenuSubmenu =>
			it.kind === 'action' || it.kind === 'submenu',
	);
}

function runSafe(fn: () => void): void {
	try {
		fn();
	} catch (err) {
		console.error(err);
	}
}

/** 先执行动作再关菜单，避免 unmount 打断；用 microtask 排到 click 之后。 */
function runThenClose(onClose: () => void, fn: () => void): void {
	runSafe(fn);
	queueMicrotask(onClose);
}

export function showContextMenu(
	event: ReactMouseEvent | MouseEvent,
	items: ContextMenuItem[],
	ariaLabel?: string,
): void {
	event.preventDefault();
	event.stopPropagation();
	if (items.length === 0) {
		return;
	}
	openContextMenu({
		x: event.clientX,
		y: event.clientY,
		items,
		ariaLabel,
	});
}

function MenuRowButton({
	item,
	active,
	expanded,
	onHover,
	onSelect,
	onFocus,
}: {
	item: ContextMenuAction | ContextMenuSubmenu;
	active: boolean;
	expanded?: boolean;
	onHover: () => void;
	onSelect: () => void;
	onFocus: () => void;
}) {
	const disabled = Boolean(item.disabled);
	const danger = item.kind === 'action' && item.danger;
	return (
		<button
			type="button"
			role="menuitem"
			aria-disabled={disabled || undefined}
			aria-haspopup={item.kind === 'submenu' ? 'menu' : undefined}
			aria-expanded={item.kind === 'submenu' ? Boolean(expanded) : undefined}
			disabled={disabled}
			tabIndex={-1}
			onMouseEnter={onHover}
			onFocus={onFocus}
			onMouseDown={e => {
				// 避免 mousedown 抢焦点 / 触发外层关闭竞态
				e.preventDefault();
				e.stopPropagation();
			}}
			onClick={e => {
				e.preventDefault();
				e.stopPropagation();
				if (!disabled) {
					onSelect();
				}
			}}
			className={cn(
				'xy-ctx-row flex h-7 w-full items-center gap-2 rounded-[5px] px-2 text-left text-[12.5px] leading-none transition-colors duration-75',
				disabled
					? 'cursor-default text-mute/40'
					: danger
						? 'text-danger'
						: 'text-ink-soft',
				active && !disabled && (danger ? 'bg-danger/10' : 'bg-glass-hover text-ink'),
			)}
		>
			<span className="min-w-0 flex-1 truncate">{item.label}</span>
			{item.kind === 'action' && item.shortcut ? (
				<span className="shrink-0 font-mono text-[10px] tracking-tight text-mute/55">
					{item.shortcut}
				</span>
			) : null}
			{item.kind === 'submenu' ? (
				<ChevronRight
					className="h-3 w-3 shrink-0 text-mute/60"
					strokeWidth={1.8}
				/>
			) : null}
		</button>
	);
}

function SubmenuPanel({
	parentRect,
	items,
	onCloseAll,
}: {
	parentRect: DOMRect;
	items: ContextMenuItem[];
	onCloseAll: () => void;
}) {
	const ref = useRef<HTMLDivElement>(null);
	const [pos, setPos] = useState({
		left: parentRect.right + 4,
		top: parentRect.top,
	});

	useLayoutEffect(() => {
		const el = ref.current;
		if (!el) {
			return;
		}
		const w = el.offsetWidth;
		const h = el.offsetHeight;
		let left = parentRect.right + 4;
		if (left + w > window.innerWidth - MENU_PAD) {
			left = parentRect.left - w - 4;
		}
		const {top} = clampPos(left, parentRect.top, w, h);
		setPos({left: Math.max(MENU_PAD, left), top});
	}, [parentRect]);

	return (
		<div
			ref={ref}
			role="menu"
			{...{[MENU_ATTR]: ''}}
			className="xy-ctx-menu fixed z-[110] rounded-md border border-line/60 p-1 shadow-lg"
			style={{left: pos.left, top: pos.top, minWidth: 148}}
			onContextMenu={e => e.preventDefault()}
		>
			{items.map((item, i) => {
				if (item.kind === 'sep') {
					return (
						<MenuSeparator key={`sep-${i}`} />
					);
				}
				return (
					<MenuRowButton
						key={item.id}
						item={item}
						active={false}
						onHover={() => undefined}
						onFocus={() => undefined}
						onSelect={() => {
							if (item.kind === 'action') {
								runThenClose(onCloseAll, item.onSelect);
							}
						}}
					/>
				);
			})}
		</div>
	);
}

function ContextMenuPanel({
	x,
	y,
	items,
	ariaLabel,
	onClose,
}: {
	x: number;
	y: number;
	items: ContextMenuItem[];
	ariaLabel: string;
	onClose: () => void;
}) {
	const menuId = useId();
	const escId = `context-menu-${menuId}`;
	const menuRef = useRef<HTMLDivElement>(null);
	const [pos, setPos] = useState({left: x, top: y});
	const [focusIdx, setFocusIdx] = useState(0);
	const [submenuId, setSubmenuId] = useState<string | null>(null);
	const [submenuAnchor, setSubmenuAnchor] = useState<DOMRect | null>(null);
	const actions = actionableItems(items);

	useLayoutEffect(() => {
		const el = menuRef.current;
		if (!el) {
			return;
		}
		setPos(clampPos(x, y, el.offsetWidth, el.offsetHeight));
	}, [x, y, items]);

	useEffect(() => {
		pushEscLayer(escId, onClose);
		return () => popEscLayer(escId);
	}, [escId, onClose]);

	useEffect(() => {
		const onPointerDown = (event: PointerEvent) => {
			const t = event.target;
			if (t instanceof Element && t.closest(`[${MENU_ATTR}]`)) {
				return;
			}
			onClose();
		};
		// 等当前右键手势结束再监听，避免立刻关掉
		const t = window.setTimeout(() => {
			document.addEventListener('pointerdown', onPointerDown, true);
		}, 0);
		return () => {
			window.clearTimeout(t);
			document.removeEventListener('pointerdown', onPointerDown, true);
		};
	}, [onClose]);

	const openSubmenuAt = useCallback((id: string, el: HTMLElement | null) => {
		setSubmenuId(id);
		setSubmenuAnchor(el?.getBoundingClientRect() ?? null);
	}, []);

	const activate = useCallback(
		(item: ContextMenuAction | ContextMenuSubmenu, el?: HTMLElement | null) => {
			if (item.disabled) {
				return;
			}
			if (item.kind === 'submenu') {
				openSubmenuAt(item.id, el ?? null);
				return;
			}
			runThenClose(onClose, item.onSelect);
		},
		[onClose, openSubmenuAt],
	);

	const onKeyDown = useCallback(
		(event: ReactKeyboardEvent) => {
			if (event.key === 'ArrowDown') {
				event.preventDefault();
				setFocusIdx(i => (i + 1) % Math.max(actions.length, 1));
				setSubmenuId(null);
				return;
			}
			if (event.key === 'ArrowUp') {
				event.preventDefault();
				setFocusIdx(
					i => (i - 1 + actions.length) % Math.max(actions.length, 1),
				);
				setSubmenuId(null);
				return;
			}
			if (event.key === 'ArrowRight') {
				const item = actions[focusIdx];
				if (item?.kind === 'submenu' && !item.disabled) {
					event.preventDefault();
					const buttons = menuRef.current?.querySelectorAll('[role="menuitem"]');
					openSubmenuAt(item.id, (buttons?.[focusIdx] as HTMLElement) ?? null);
				}
				return;
			}
			if (event.key === 'ArrowLeft') {
				if (submenuId) {
					event.preventDefault();
					setSubmenuId(null);
					setSubmenuAnchor(null);
				}
				return;
			}
			if (event.key === 'Enter' || event.key === ' ') {
				const item = actions[focusIdx];
				if (item) {
					event.preventDefault();
					const buttons = menuRef.current?.querySelectorAll('[role="menuitem"]');
					activate(item, (buttons?.[focusIdx] as HTMLElement) ?? null);
				}
			}
		},
		[actions, activate, focusIdx, openSubmenuAt, submenuId],
	);

	useEffect(() => {
		menuRef.current?.focus();
	}, []);

	const submenuItem =
		submenuId != null
			? actions.find(
					(it): it is ContextMenuSubmenu =>
						it.kind === 'submenu' && it.id === submenuId,
				)
			: null;

	let actionCursor = -1;

	return createPortal(
		<>
			<div
				ref={menuRef}
				id={menuId}
				role="menu"
				tabIndex={-1}
				aria-label={ariaLabel}
				{...{[MENU_ATTR]: ''}}
				className="xy-ctx-menu fixed z-[100] rounded-md border border-line/60 p-1 outline-none shadow-lg"
				style={{left: pos.left, top: pos.top, minWidth: MENU_MIN_W}}
				onKeyDown={onKeyDown}
				onContextMenu={e => e.preventDefault()}
			>
				{items.map((item, i) => {
					if (item.kind === 'sep') {
						return (
							<MenuSeparator key={`sep-${i}`} />
						);
					}
					actionCursor += 1;
					const idx = actionCursor;
					const active = idx === focusIdx;
					return (
						<MenuRowButton
							key={item.id}
							item={item}
							active={active}
							expanded={item.kind === 'submenu' && submenuId === item.id}
							onHover={() => {
								setFocusIdx(idx);
								if (item.kind === 'submenu' && !item.disabled) {
									openSubmenuAt(
										item.id,
										menuRef.current?.querySelectorAll('[role="menuitem"]')[
											idx
										] as HTMLElement,
									);
								} else {
									setSubmenuId(null);
									setSubmenuAnchor(null);
								}
							}}
							onFocus={() => setFocusIdx(idx)}
							onSelect={() => {
								const buttons =
									menuRef.current?.querySelectorAll('[role="menuitem"]');
								activate(item, (buttons?.[idx] as HTMLElement) ?? null);
							}}
						/>
					);
				})}
			</div>
			{submenuItem && submenuAnchor ? (
				<SubmenuPanel
					parentRect={submenuAnchor}
					items={submenuItem.items}
					onCloseAll={onClose}
				/>
			) : null}
		</>,
		document.body,
	);
}

export function ContextMenuHost(): ReactNode {
	const menu = useContextMenuStore(s => s.menu);
	const close = useContextMenuStore(s => s.close);

	if (!menu) {
		return null;
	}

	return (
		<ContextMenuPanel
			x={menu.x}
			y={menu.y}
			items={menu.items}
			ariaLabel={menu.ariaLabel}
			onClose={close}
		/>
	);
}
