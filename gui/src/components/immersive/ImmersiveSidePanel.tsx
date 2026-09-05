import {
	ChevronDown,
	ChevronsRight,
	CircleGauge,
	FolderGit2,
	Puzzle,
	Sparkles,
	Plus,
	X,
} from 'lucide-react';
import {useEffect, useRef, useState} from 'react';
import {ImmersiveTodo} from './ImmersiveTodo';
import {useChatUiStore} from '@/stores/chatUiStore';
import {newSession, openPageView, openSession} from '@/lib/appNav';

/**
 * 沉浸模式右板（smoke-test #5 重做）：
 * - 收纳原 ImmersiveHeader 的「会话标题 / 新对话 / 用量 / 插件 / 工作区 / 退出」，
 * - 与 ImmersiveTodo 共用同一玻璃面板（顶部条因此去除），
 * - 受父级 ImmersiveLayer 控制开合（`Ctrl/Cmd+B` 切换，`Esc` 逐层退出）。
 */
export function ImmersiveSidePanel({onCollapse}: {onCollapse: () => void}) {
	const setImmersive = useChatUiStore(s => s.setImmersive);
	const sessions = useChatUiStore(s => s.sessions);
	const activeId = useChatUiStore(s => s.activeId);
	const spaces = useChatUiStore(s => s.spaces);
	const activeSpaceId = useChatUiStore(s => s.activeSpaceId);
	const setActiveSpace = useChatUiStore(s => s.setActiveSpace);

	const [titleOpen, setTitleOpen] = useState(false);
	const [wsOpen, setWsOpen] = useState(false);
	const titleRef = useRef<HTMLButtonElement>(null);
	const wsRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		if (!titleOpen && !wsOpen) {
			return;
		}
		const handler = (e: MouseEvent) => {
			const target = e.target as Node | null;
			if (!target) {
				return;
			}
			if (
				titleOpen &&
				titleRef.current &&
				!titleRef.current.parentElement?.contains(target)
			) {
				setTitleOpen(false);
			}
			if (wsOpen && wsRef.current && !wsRef.current.contains(target)) {
				setWsOpen(false);
			}
		};
		window.addEventListener('mousedown', handler);
		return () => window.removeEventListener('mousedown', handler);
	}, [titleOpen, wsOpen]);

	const activeTitle =
		sessions.find(s => s.id === activeId)?.title?.trim() || '新对话';
	const ws = spaces.find(w => w.id === activeSpaceId);

	const exitImmersive = () => setImmersive(false);
	const newChat = () => {
		// 统一入口（lib/appNav）：新建会话 + 路由。
		void newSession();
	};
	// 页面视图是真路由：先退沉浸态，再导航（导航本身即打开 /usage、/plugins）。
	const goPageView = (kind: 'usage' | 'plugins') => {
		exitImmersive();
		openPageView(kind);
	};
	const switchSession = async (id: string) => {
		await openSession(id);
		setTitleOpen(false);
	};

	const iconBtn =
		'xy-press flex h-9 flex-1 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-white/85 hover:bg-white/10';

	return (
		<aside
			aria-label="沉浸模式侧板"
			className="xy-immersive-panel pointer-events-auto absolute right-4 top-4 bottom-4 z-30 flex w-72 flex-col rounded-2xl"
		>
			<header className="flex items-center gap-2 px-3 pt-3 pb-2">
				<Sparkles className="size-3.5 text-accent" />
				<span className="text-[12px] font-medium tracking-wide text-white/85">
					沉浸
				</span>
				<button
					type="button"
					aria-label="折叠右板"
					title="折叠右板（Ctrl/Cmd+B）"
					onClick={onCollapse}
					className="ml-auto rounded-md p-1 text-white/65 hover:bg-white/10 hover:text-white"
				>
					<ChevronsRight className="size-4" />
				</button>
			</header>

			{/* 会话标题 + 切换 */}
			<div className="relative px-3 pb-2">
				<button
					ref={titleRef}
					type="button"
					aria-haspopup="menu"
					aria-expanded={titleOpen}
					onClick={() => {
						setTitleOpen(v => !v);
						setWsOpen(false);
					}}
					className="flex w-full items-center gap-2 rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-left text-[13px] text-white/90 hover:bg-white/10"
				>
					<span aria-hidden className="text-ok">●</span>
					<span className="min-w-0 flex-1 truncate">{activeTitle}</span>
					<ChevronDown className="size-3 shrink-0 opacity-70" />
				</button>
				{titleOpen ? (
					<div className="xy-menu-flyout absolute left-3 right-3 top-full z-40 mt-1 max-h-60 overflow-y-auto rounded-xl">
						<div className="px-3 py-2 text-[11px] text-mute">切换对话</div>
						{sessions.length ? (
							sessions.map(s => (
								<button
									key={s.id}
									type="button"
									className="xy-menu-row mx-1.5 flex w-[calc(100%-12px)] items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px]"
									onClick={() => void switchSession(s.id)}
								>
									<span className="min-w-0 flex-1 truncate text-ink-soft">
										{s.title?.trim() || '新对话'}
									</span>
									{s.id === activeId ? (
										<span className="shrink-0 text-accent">当前</span>
									) : null}
								</button>
							))
						) : (
							<div className="px-3 pb-2 text-[12px] text-mute">暂无对话</div>
						)}
					</div>
				) : null}
			</div>

			{/* 功能按钮 */}
			<div className="px-3 pb-3">
				<div className="flex items-center gap-1.5">
					<button
						type="button"
						aria-label="新对话"
						title="新对话"
						className={iconBtn}
						onClick={() => void newChat()}
					>
						<Plus className="size-4" />
					</button>
					<button
						type="button"
						aria-label="用量"
						title="用量"
						className={iconBtn}
						onClick={() => goPageView('usage')}
					>
						<CircleGauge className="size-4" />
					</button>
					<button
						type="button"
						aria-label="插件 / MCP"
						title="插件 / MCP"
						className={iconBtn}
						onClick={() => goPageView('plugins')}
					>
						<Puzzle className="size-4" />
					</button>
				</div>
				<div className="relative mt-1.5" ref={wsRef}>
					<button
						type="button"
						aria-haspopup="menu"
						aria-expanded={wsOpen}
						onClick={() => {
							setWsOpen(v => !v);
							setTitleOpen(false);
						}}
						className="flex w-full items-center gap-2 rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-left text-[12.5px] text-white/85 hover:bg-white/10"
					>
						<FolderGit2 className="size-4 shrink-0" />
						<span className="min-w-0 flex-1 truncate">
							{ws?.name || '工作区'}
						</span>
						<ChevronDown className="size-3 shrink-0 opacity-70" />
					</button>
					{wsOpen ? (
						<div className="xy-menu-flyout absolute left-0 right-0 top-full z-40 mt-1 max-h-60 overflow-y-auto rounded-xl">
							<div className="px-3 py-2 text-[11px] text-mute">切换工作区</div>
							{spaces.length ? (
								spaces.map(w => (
									<button
										key={w.id}
										type="button"
										className="xy-menu-row mx-1.5 flex w-[calc(100%-12px)] items-center gap-2 px-2.5 py-1.5 text-left text-[12.5px]"
										onClick={() => {
											setWsOpen(false);
											void setActiveSpace(w.id);
										}}
									>
										<span className="min-w-0 flex-1 truncate text-ink-soft">
											{w.name}
										</span>
										{w.id === activeSpaceId ? (
											<span className="shrink-0 text-accent">当前</span>
										) : null}
									</button>
								))
							) : (
								<div className="px-3 pb-2 text-[12px] text-mute">暂无工作区</div>
							)}
						</div>
					) : null}
				</div>
			</div>

			{/* 今日待办（占满中间空间） */}
			<div className="min-h-0 flex-1 px-3 pb-3">
				<div className="xy-immersive-panel flex h-full min-h-0 flex-col rounded-xl">
					<ImmersiveTodo />
				</div>
			</div>

			{/* 退出沉浸 */}
			<footer className="px-3 pt-1 pb-3">
				<button
					type="button"
					onClick={exitImmersive}
					className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-2 text-[12.5px] text-white/90 hover:bg-white/10"
				>
					<X className="size-3.5" />
					退出沉浸模式
				</button>
			</footer>
		</aside>
	);
}

/** 右板折叠态下的展开把手（悬浮右缘中部）。 */
export function ImmersiveSidePanelHandle({onExpand}: {onExpand: () => void}) {
	return (
		<button
			type="button"
			aria-label="展开沉浸右板"
			title="展开右板（Ctrl/Cmd+B）"
			onClick={onExpand}
			className="xy-press pointer-events-auto absolute right-2 top-1/2 z-30 -translate-y-1/2 flex items-center gap-1 rounded-full border border-white/15 bg-white/5 px-2.5 py-2 text-white/80 backdrop-blur hover:bg-white/10"
		>
			<ChevronsRight className="size-4 rotate-180" />
			<span className="text-[11px]">右板</span>
		</button>
	);
}