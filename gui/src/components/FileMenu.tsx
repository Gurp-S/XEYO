import {useCallback, useEffect, useId, useRef, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {pickFolder} from '@/lib/openFolder';
import {isTauri} from '@/lib/tauri';
import {cn} from '@/lib/utils';
import {useChatStore} from '@/stores/chatStore';
import {useSettingsStore} from '@/stores/settingsStore';
import {useRemoteStore} from '@/stores/remoteStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {closePetWindow} from '@/pet/PetBridge';
import {useDismiss} from '@/ui/useDismiss';
import {toast} from '@/lib/toast';
import {MenuSeparator} from '@/components/ui/MenuSeparator';
import './ux-loaders.css';

type MenuItem =
	| {kind: 'action'; id: string; label: string; shortcut?: string; disabled?: boolean; onSelect: () => void}
	| {kind: 'sep'};

export function FileMenu({label = 'XEYO'}: {label?: string}) {
	const navigate = useNavigate();
	const immersive = useChatStore(s => s.immersive);
	const createSession = useChatStore(s => s.createSession);
	const openFolder = useChatStore(s => s.openFolder);
	const enterSpace = useChatStore(s => s.enterSpace);
	const openSettings = useSettingsStore(s => s.openSettings);
	const toggleRemote = useRemoteStore(s => s.toggleRemote);
	const remoteLoggedIn = useRemoteStore(s => s.loggedIn);
	const pollError = useRemoteStore(s => s.pollError);
	const [open, setOpen] = useState(false);
	const [busy, setBusy] = useState(false);
	const rootRef = useRef<HTMLDivElement>(null);
	const menuId = useId();

	const onNewAgent = useCallback(async () => {
		const id = await createSession();
		navigate(`/c/${id}`);
	}, [createSession, navigate]);

	const onOpenFolder = useCallback(async () => {
		if (busy) {
			return;
		}
		setBusy(true);
		try {
			const path = await pickFolder();
			if (!path) {
				return;
			}
			const spaceId = await openFolder(path);
			const id = await enterSpace(spaceId);
			navigate(`/c/${id}`);
		} catch (err) {
			toast.error(
				err instanceof Error ? err.message : `打开文件夹失败：${String(err)}`,
			);
		} finally {
			setBusy(false);
		}
	}, [busy, enterSpace, navigate, openFolder]);

	const onOpenTerminal = useCallback(() => {
		const ws = useWorkspaceStore.getState();
		ws.setOpen(true);
		ws.setActiveTool('terminal');
	}, []);

	const onOpenBrowser = useCallback(() => {
		const ws = useWorkspaceStore.getState();
		ws.setOpen(true);
		ws.setActiveTool('browser');
	}, []);

	const onExit = useCallback(async () => {
			if (!isTauri()) {
				toast.info('浏览器模式无窗口可关闭');
				return;
			}
			const {getCurrentWindow} = await import('@tauri-apps/api/window');
			try {
			await closePetWindow();
		} finally {
			await getCurrentWindow().close();
		}
	}, []);

	const items: MenuItem[] = [
		{
			kind: 'action',
			id: 'new-agent',
			label: '新建对话',
			shortcut: 'Ctrl+N',
			onSelect: () => void onNewAgent(),
		},
		{
			kind: 'action',
			id: 'open-folder',
			label: busy ? '正在打开…' : '打开文件夹',
			shortcut: 'Ctrl+O',
			disabled: busy,
			onSelect: () => void onOpenFolder(),
		},
		{kind: 'sep'},
		{
			kind: 'action',
			id: 'terminal',
			label: '终端',
			onSelect: onOpenTerminal,
		},
		{
			kind: 'action',
			id: 'browser',
			label: '浏览器预览',
			onSelect: onOpenBrowser,
		},
		{kind: 'sep'},
		{
			kind: 'action',
			id: 'remote',
			label: remoteLoggedIn ? '断开远程' : '远程连接',
			onSelect: () => void toggleRemote(),
		},
		{kind: 'sep'},
		{
			kind: 'action',
			id: 'settings',
			label: '设置',
			onSelect: () => openSettings(),
		},
		{kind: 'sep'},
		{
			kind: 'action',
			id: 'immersive',
			label: immersive ? '退出沉浸模式' : '沉浸模式',
			// 不挂快捷键提示：进入方向没有任何键盘键（Ctrl+B 只管沉浸内的侧板，
			// Esc 只在「已沉浸且无上层可关物」时退出）——挂 Esc 会引人白按。
			onSelect: () => {
				useChatStore.getState().setImmersive(!immersive);
			},
		},
		{kind: 'sep'},
		{
			kind: 'action',
			id: 'exit',
			label: '退出应用',
			onSelect: () => void onExit(),
		},
	];

	// 关闭配对：Esc 走 escStack 顶层（document 冒泡监听在流式期间会被「停止生成」
	// 层先吃掉 —— Esc 停回合、菜单还开着），外点关闭。原先另挂的 document
	// keydown 兜底随重构去掉：escStack 在捕获阶段就 stopPropagation，本菜单是
	// 最上层时它从不触发，不是最上层时它反而会越级关掉下层。
	useDismiss({open, onClose: () => setOpen(false), escId: 'file-menu', keepOpenRefs: [rootRef]});

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			const mod = e.ctrlKey || e.metaKey;
			if (!mod || e.altKey) {
				return;
			}
			const key = e.key.toLowerCase();
			if (key === 'o' && !e.shiftKey) {
				e.preventDefault();
				setOpen(false);
				void onOpenFolder();
			} else if (key === 'n' && !e.shiftKey) {
				e.preventDefault();
				setOpen(false);
				void onNewAgent();
			}
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [onNewAgent, onOpenFolder]);

	return (
		<div ref={rootRef} className="relative">
			<button
				type="button"
				aria-label="应用菜单"
				aria-haspopup="menu"
				aria-expanded={open}
				aria-controls={menuId}
				onMouseDown={e => e.stopPropagation()}
				onClick={() => setOpen(v => !v)}
				className={cn(
					'xy-icon-btn xy-no-drag flex items-center rounded-md p-1 text-ink-soft hover:bg-glass-hover hover:text-ink',
					open && 'bg-glass-hover text-ink',
				)}
			>
				<span className="pointer-events-none select-none whitespace-nowrap leading-none">
					<span className="text-[12.5px] font-semibold text-ink-soft">{label}</span>
				</span>
			</button>
			{open ? (
				<div
					id={menuId}
					role="menu"
					className="xy-menu-flyout absolute top-full left-0 z-50 mt-1 min-w-[220px] rounded-lg border border-line/50 py-1"
				>
					{items.map((item, i) =>
						item.kind === 'sep' ? (
							<MenuSeparator key={`sep-${i}`} />
						) : (
							<button
								key={item.id}
								type="button"
								role="menuitem"
								disabled={item.disabled}
								onClick={() => {
									if (item.disabled) {
										return;
									}
									setOpen(false);
									item.onSelect();
								}}
								className={cn(
									'flex w-full items-center justify-between gap-6 px-3 py-1.5 text-left text-[13px]',
									item.disabled
										? 'cursor-default text-mute/55'
										: 'text-ink-soft hover:bg-glass-hover hover:text-ink',
								)}
							>
								<span className="flex min-w-0 items-center gap-2">
								{item.id === 'open-folder' && busy ? (
									<span className="xy-spinner" aria-hidden="true" />
								) : null}
								{item.id === 'remote' ? (
									<span
										className={cn(
											'h-1.5 w-1.5 shrink-0 rounded-full',
											pollError
												? 'bg-danger'
												: remoteLoggedIn
													? 'bg-ok'
													: 'bg-mute/40',
										)}
									/>
								) : null}
								<span className="truncate">{item.label}</span>
							</span>
								{item.shortcut ? (
									<span className="shrink-0 font-mono text-[11px] text-mute/70">
										{item.shortcut}
									</span>
								) : null}
							</button>
						),
					)}
				</div>
			) : null}
		</div>
	);
}
