import type {CSSProperties, MouseEvent} from 'react';
import {Minus, Square, Copy, Moon, PanelRightClose, PanelRightOpen, Sun, X} from 'lucide-react';
import {FileMenu} from '@/components/FileMenu';
import {SettingsModal} from '@/components/SettingsModal';
import {isTauri} from '@/lib/tauri';
import {cn} from '@/lib/utils';
import {useEffect, useRef, useState} from 'react';
import {useSettingsStore} from '@/stores/settingsStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {closePetWindow} from '@/pet/PetBridge';
import {isDarkScheme} from '@/theme/catalog';
import {ThemePicker} from '@/theme/ThemePicker';

async function win() {
	const {getCurrentWindow} = await import('@tauri-apps/api/window');
	return getCurrentWindow();
}

async function closeAppWindow() {
	try {
		await closePetWindow();
	} finally {
		await (await win()).close();
	}
}

function startWinDrag() {
	void win().then(w => w.startDragging());
}

const noDragStyle = {
	WebkitAppRegion: 'no-drag',
	appRegion: 'no-drag',
} as CSSProperties;

const chromeBtn =
	'xy-icon-btn xy-no-drag relative z-10 cursor-pointer rounded-lg p-1.5 text-mute hover:bg-ink/5 hover:text-ink';

/** 应用 chrome：品牌图标打开文件菜单。窗口按钮仅在 Tauri 中。 */
export function TitleBar() {
	const desktop = isTauri();
	const [maximized, setMaximized] = useState(false);
	const [themeOpen, setThemeOpen] = useState(false);
	const themeWrapRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		if (!desktop) {
			return;
		}
		let disposed = false;
		let unlisten: (() => void) | undefined;
		void win().then(async current => {
			if (disposed) {
				return;
			}
			setMaximized(await current.isMaximized());
			unlisten = await current.onResized(async () => {
				setMaximized(await current.isMaximized());
			});
		});
		return () => {
			disposed = true;
			unlisten?.();
		};
	}, [desktop]);

	// 最大化时整窗铺满屏幕：去掉 #root 圆角与边框（CSS 据此切换）。
	useEffect(() => {
		const html = document.documentElement;
		if (maximized) {
			html.setAttribute('data-window-maximized', '1');
		} else {
			html.removeAttribute('data-window-maximized');
		}
		return () => html.removeAttribute('data-window-maximized');
	}, [maximized]);

	useEffect(() => {
		if (!themeOpen) {
			return;
		}
		const onDoc = (e: Event) => {
			const t = e.target as Node | null;
			if (themeWrapRef.current && t && !themeWrapRef.current.contains(t)) {
				setThemeOpen(false);
			}
		};
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				setThemeOpen(false);
			}
		};
		document.addEventListener('mousedown', onDoc);
		document.addEventListener('keydown', onKey);
		return () => {
			document.removeEventListener('mousedown', onDoc);
			document.removeEventListener('keydown', onKey);
		};
	}, [themeOpen]);

	const theme = useSettingsStore(s => s.theme);
	const update = useSettingsStore(s => s.update);
	const settingsOpen = useSettingsStore(s => s.settingsModalOpen);
	const closeSettings = useSettingsStore(s => s.closeSettings);
	const titleBarDivider = useSettingsStore(s => s.titleBarDivider !== false);
	const darkScheme = isDarkScheme(theme);

	const workspaceOpen = useWorkspaceStore(s => s.open);
	const setWorkspaceOpen = useWorkspaceStore(s => s.setOpen);
	const collapseWorkspace = useWorkspaceStore(s => s.collapseWorkspace);
	const toggleWorkspace = () => {
		if (workspaceOpen) {
			collapseWorkspace();
		} else {
			setWorkspaceOpen(true);
		}
	};

	const stopNativeDrag = (e: MouseEvent) => {
		e.stopPropagation();
	};

	const themeBtn = (
		<div ref={themeWrapRef} className="relative">
			<button
				type="button"
				aria-label="选择主题"
				aria-expanded={themeOpen}
				aria-haspopup="listbox"
				className={cn(chromeBtn, themeOpen && 'text-accent hover:text-accent')}
				style={noDragStyle}
				onMouseDown={stopNativeDrag}
				onClick={() => setThemeOpen(o => !o)}
			>
				{darkScheme ? (
					<Sun className="pointer-events-none h-3.5 w-3.5" strokeWidth={1.75} />
				) : (
					<Moon className="pointer-events-none h-3.5 w-3.5" strokeWidth={1.75} />
				)}
			</button>
			{themeOpen ? (
				<div
					className="xy-menu-flyout absolute right-0 top-[calc(100%+6px)] z-[80] rounded-2xl border border-line/50 p-2"
					style={noDragStyle}
					onMouseDown={stopNativeDrag}
				>
					<ThemePicker
						compact
						value={theme}
						onChange={id => {
							update({theme: id});
							setThemeOpen(false);
						}}
					/>
				</div>
			) : null}
		</div>
	);

	return (
		<>
			<div
				className={cn(
					'xy-titlebar relative z-50 flex h-10 shrink-0 items-center px-3',
					titleBarDivider && 'xy-soft-rule-b',
				)}
			>
				<div
					className="xy-no-drag relative z-10 flex shrink-0 items-center gap-1.5 pl-0.5"
					style={noDragStyle}
				>
					<FileMenu />
				</div>
				<div
					className="xy-titlebar-drag h-full min-w-0 flex-1 cursor-default"
					onMouseDown={e => {
						if (!desktop || e.button !== 0) {
							return;
						}
						if (
							(e.target as HTMLElement).closest(
								'button, a, [data-xy-remote-btn]',
							)
						) {
							return;
						}
						e.preventDefault();
						if (e.clientY <= 6) {
							void win().then(w => w.startResizeDragging('North'));
							return;
						}
						startWinDrag();
					}}
				/>
				<div
					className="xy-no-drag relative z-10 flex shrink-0 items-center gap-1.5"
					style={noDragStyle}
				>
					{themeBtn}
					<button
						type="button"
						aria-label={workspaceOpen ? '收起工作区' : '展开工作区'}
						className={cn(chromeBtn, workspaceOpen && 'text-accent hover:text-accent-hover')}
						style={noDragStyle}
						onMouseDown={stopNativeDrag}
						onClick={() => toggleWorkspace()}
					>
						{workspaceOpen ? (
							<PanelRightClose className="pointer-events-none h-3.5 w-3.5" strokeWidth={1.75} />
						) : (
							<PanelRightOpen className="pointer-events-none h-3.5 w-3.5" strokeWidth={1.75} />
						)}
					</button>
					{desktop ? (
						<div className="flex items-center gap-1">
							<button
								type="button"
								aria-label="最小化"
								className={`${chromeBtn}`}
								style={noDragStyle}
								onMouseDown={stopNativeDrag}
								onClick={() => void win().then(w => w.minimize())}
							>
								<Minus className="pointer-events-none h-3.5 w-3.5" strokeWidth={1.75} />
							</button>
							<button
								type="button"
								aria-label={maximized ? '还原' : '最大化'}
								className={`${chromeBtn}`}
								style={noDragStyle}
								onMouseDown={stopNativeDrag}
								onClick={() => void win().then(w => w.toggleMaximize())}
							>
								{maximized ? (
									<Copy
										className="pointer-events-none h-3.5 w-3.5"
										strokeWidth={1.75}
									/>
								) : (
									<Square
										className="pointer-events-none h-3.5 w-3.5"
										strokeWidth={1.75}
									/>
								)}
							</button>
							<button
								type="button"
								aria-label="关闭"
								className="xy-icon-btn xy-no-drag relative z-10 cursor-pointer rounded-lg p-1.5 text-mute hover:bg-danger/10 hover:text-danger"
								style={noDragStyle}
								onMouseDown={stopNativeDrag}
								onClick={() => void closeAppWindow()}
							>
								<X className="pointer-events-none h-3.5 w-3.5" strokeWidth={1.75} />
							</button>
						</div>
					) : null}
				</div>
			</div>
			<SettingsModal open={settingsOpen} onClose={() => closeSettings()} />
		</>
	);
}
