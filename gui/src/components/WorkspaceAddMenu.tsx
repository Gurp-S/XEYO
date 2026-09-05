import {
	ChevronLeft,
	ChevronRight,
	Cloud,
	Folder,
	FolderInput,
	FolderPlus,
	Monitor,
	Plus,
} from 'lucide-react';
import {
	useCallback,
	useEffect,
	useId,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
	type KeyboardEvent as ReactKeyboardEvent,
	type ReactNode,
	type RefObject,
} from 'react';
import {createPortal} from 'react-dom';
import {pickFolder} from '@/lib/openFolder';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {looksLikeFsPath, uniqueParentDirs} from '@/lib/paths';
import {toast} from '@/lib/toast';
import {MenuSeparator} from '@/components/ui/MenuSeparator';
import {
	cloneDestPath,
	createDirectory,
	createEmptyProject,
	expandGitUrl,
	gitClone,
	listGitRepos,
	pickNewFolderPath,
} from '@/lib/workspaceAdd';

export type WorkspaceRecent = {
	path: string;
	name: string;
};

type MenuView = 'root' | 'this-pc' | 'cloud';

type WorkspaceAddButtonProps = {
	recents: WorkspaceRecent[];
	busy?: boolean;
	onOpenPath: (path: string) => Promise<void>;
};

export function WorkspaceAddButton({
	recents,
	busy = false,
	onOpenPath,
}: WorkspaceAddButtonProps) {
	const [open, setOpen] = useState(false);
	const btnRef = useRef<HTMLButtonElement>(null);
	const menuId = useId();

	return (
		<div className="add-menu-container relative">
			<button
				ref={btnRef}
				type="button"
				aria-label={busy ? '正在打开…' : '添加工作区'}
				aria-haspopup="dialog"
				aria-expanded={open}
				aria-controls={open ? menuId : undefined}
				disabled={busy}
				onClick={e => {
					e.stopPropagation();
					setOpen(v => !v);
				}}
				className="xy-icon-btn rounded-md p-1 text-current hover:bg-glass-hover hover:text-current disabled:opacity-60"
			>
				{busy ? (
					<span className="xy-spinner" aria-hidden="true" />
				) : (
					<Plus className="h-3.5 w-3.5" />
				)}
			</button>
			{open ? (
				<WorkspaceAddMenu
					id={menuId}
					anchorRef={btnRef}
					recents={recents}
					busy={busy}
					onOpenPath={onOpenPath}
					onClose={() => setOpen(false)}
				/>
			) : null}
		</div>
	);
}

function WorkspaceAddMenu({
	id,
	anchorRef,
	recents,
	busy,
	onOpenPath,
	onClose,
}: {
	id: string;
	anchorRef: RefObject<HTMLButtonElement | null>;
	recents: WorkspaceRecent[];
	busy: boolean;
	onOpenPath: (path: string) => Promise<void>;
	onClose: () => void;
}) {
	const menuRef = useRef<HTMLDivElement>(null);
	const searchRef = useRef<HTMLInputElement>(null);
	const [view, setView] = useState<MenuView>('root');
	const [query, setQuery] = useState('');
	const [pos, setPos] = useState<{top: number; left: number} | null>(null);
	const [localRepos, setLocalRepos] = useState<string[]>([]);
	const [loadingRepos, setLoadingRepos] = useState(false);

	const filteredRecents = useMemo(() => {
		const q = query.trim().toLowerCase();
		if (!q) {
			return recents;
		}
		return recents.filter(
			r =>
				r.path.toLowerCase().includes(q) || r.name.toLowerCase().includes(q),
		);
	}, [query, recents]);

	const filteredLocal = useMemo(() => {
		const q = query.trim().toLowerCase();
		if (!q) {
			return localRepos;
		}
		return localRepos.filter(p => p.toLowerCase().includes(q));
	}, [localRepos, query]);

	useLayoutEffect(() => {
		const update = () => {
			const btn = anchorRef.current;
			const el = menuRef.current;
			if (!btn) {
				return;
			}
			const rect = btn.getBoundingClientRect();
			const width = el?.offsetWidth || 280;
			const height = el?.offsetHeight || 320;
			const pad = 8;
			let left = rect.left;
			if (left + width > window.innerWidth - pad) {
				left = Math.max(pad, rect.right - width);
			}
			let top = rect.bottom + 6;
			if (top + height > window.innerHeight - pad) {
				top = Math.max(pad, rect.top - height - 6);
			}
			setPos({top, left});
		};
		update();
		window.addEventListener('resize', update);
		window.addEventListener('scroll', update, true);
		return () => {
			window.removeEventListener('resize', update);
			window.removeEventListener('scroll', update, true);
		};
	}, [anchorRef, view, filteredRecents.length, filteredLocal.length]);

	useEffect(() => {
		searchRef.current?.focus();
	}, [view]);

	useEffect(() => {
		pushEscLayer('workspace-add', () => {
			if (view !== 'root') {
				setView('root');
				setQuery('');
				return;
			}
			onClose();
		});
		return () => popEscLayer('workspace-add');
	}, [onClose, view]);

	useEffect(() => {
		const onDoc = (e: MouseEvent) => {
			const t = e.target as Node | null;
			if (!t) {
				return;
			}
			if (menuRef.current?.contains(t) || anchorRef.current?.contains(t)) {
				return;
			}
			onClose();
		};
		document.addEventListener('mousedown', onDoc);
		return () => document.removeEventListener('mousedown', onDoc);
	}, [anchorRef, onClose]);

	useEffect(() => {
		if (view !== 'this-pc') {
			return;
		}
		let cancelled = false;
		setLoadingRepos(true);
		void listGitRepos(uniqueParentDirs(recents.map(r => r.path))).then(
			paths => {
				if (!cancelled) {
					setLocalRepos(paths);
					setLoadingRepos(false);
				}
			},
		);
		return () => {
			cancelled = true;
		};
	}, [recents, view]);

	const openPath = useCallback(
		async (path: string) => {
			onClose();
			await onOpenPath(path);
		},
		[onClose, onOpenPath],
	);

	const runAndClose = useCallback(
		async (fn: () => Promise<void>) => {
			onClose();
			try {
				await fn();
			} catch (err) {
				toast.error(
					err instanceof Error ? err.message : `操作失败：${String(err)}`,
				);
			}
		},
		[onClose],
	);

	const onUseExisting = useCallback(() => {
		void runAndClose(async () => {
			const path = await pickFolder('打开文件夹');
			if (path) {
				await onOpenPath(path);
			}
		});
	}, [onOpenPath, runAndClose]);

	const onNewFolder = useCallback(() => {
		void runAndClose(async () => {
			const path = await pickNewFolderPath(
				'选择新建位置',
				'新文件夹名称',
				'例如 my-project',
			);
			if (!path) {
				return;
			}
			await createDirectory(path);
			await onOpenPath(path);
		});
	}, [onOpenPath, runAndClose]);

	const onStartFromScratch = useCallback(() => {
		void runAndClose(async () => {
			const path = await pickNewFolderPath(
				'选择项目位置',
				'项目名称',
				'例如 my-app',
			);
			if (!path) {
				return;
			}
			await createEmptyProject(path);
			await onOpenPath(path);
		});
	}, [onOpenPath, runAndClose]);

	const onBrowseThisPc = useCallback(() => {
		void runAndClose(async () => {
			const path = await pickFolder('在此电脑上打开');
			if (path) {
				await onOpenPath(path);
			}
		});
	}, [onOpenPath, runAndClose]);

	const onClone = useCallback(async () => {
		const url = expandGitUrl(query);
		if (!url) {
			toast.info('粘贴 Git URL，或输入 owner/repo');
			return;
		}
		onClose();
		try {
			const parent = await pickFolder('选择克隆位置');
			if (!parent) {
				return;
			}
			const dest = cloneDestPath(parent, url);
			toast.info('正在克隆仓库…');
			await gitClone(url, dest);
			await onOpenPath(dest);
		} catch (err) {
			toast.error(
				err instanceof Error ? err.message : `克隆失败：${String(err)}`,
			);
		}
	}, [onClose, onOpenPath, query]);

	const onSearchKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
		if (e.key !== 'Enter') {
			return;
		}
		e.preventDefault();
		if (view === 'cloud') {
			void onClone();
			return;
		}
		const q = query.trim();
		if (view === 'this-pc' && filteredLocal[0]) {
			void openPath(filteredLocal[0]);
			return;
		}
		if (filteredRecents[0]) {
			void openPath(filteredRecents[0].path);
			return;
		}
		if (looksLikeFsPath(q)) {
			void openPath(q);
		}
	};

	const searchPlaceholder =
		view === 'cloud'
			? 'Paste git URL or owner/repo'
			: 'Search folders, repos...';

	const menu = (
		<div
			ref={menuRef}
			id={id}
			role="dialog"
			aria-label="添加工作区"
			className="xy-menu-flyout fixed z-[90] w-[280px] overflow-hidden rounded-2xl border border-line/50 py-1.5"
			style={
				pos
					? {top: pos.top, left: pos.left}
					: {top: 0, left: 0, visibility: 'hidden'}
			}
			onMouseDown={e => e.stopPropagation()}
		>
			{view !== 'root' ? (
				<button
					type="button"
					onClick={() => {
						setView('root');
						setQuery('');
					}}
					className="xy-menu-row mx-1 mb-0.5 flex w-[calc(100%-8px)] items-center gap-1.5 px-2 py-1.5 text-left text-[12.5px] text-ink-soft"
				>
					<ChevronLeft className="h-3.5 w-3.5 shrink-0" />
					<span>{view === 'this-pc' ? 'On This PC' : 'Cloud'}</span>
				</button>
			) : null}

			<div className="px-2 pb-1.5">
				<input
					ref={searchRef}
					type="text"
					value={query}
					onChange={e => setQuery(e.target.value)}
					onKeyDown={onSearchKey}
					placeholder={searchPlaceholder}
					className="xy-menu-frosted-input w-full rounded-lg border px-2.5 py-1.5 text-[13px] text-ink outline-none placeholder:text-mute focus:border-line"
					autoComplete="off"
					spellCheck={false}
				/>
			</div>

			<div className="max-h-[min(420px,70vh)] overflow-y-auto">
				{view === 'root' ? (
					<>
						<SectionLabel>Recents</SectionLabel>
						{filteredRecents.length === 0 ? (
							<p className="px-3 py-2 text-[12px] text-mute">无最近文件夹</p>
						) : (
							filteredRecents.map(item => (
								<PathRow
									key={item.path}
									path={item.path}
									disabled={busy}
									onSelect={() => void openPath(item.path)}
								/>
							))
						)}

						<SectionLabel>Repos</SectionLabel>
						<ActionRow
							icon={<Monitor className="h-3.5 w-3.5" />}
							label="On This PC"
							chevron
							onSelect={() => {
								setQuery('');
								setView('this-pc');
							}}
						/>
						<ActionRow
							icon={<Cloud className="h-3.5 w-3.5" />}
							label="Cloud"
							chevron
							onSelect={() => {
								setQuery('');
								setView('cloud');
							}}
						/>
						<ActionRow
							icon={<Plus className="h-3.5 w-3.5" />}
							label="Start from scratch"
							disabled={busy}
							onSelect={onStartFromScratch}
						/>

						<MenuSeparator />

						<ActionRow
							icon={<FolderInput className="h-3.5 w-3.5" />}
							label="Use Existing..."
							chevron
							disabled={busy}
							onSelect={onUseExisting}
						/>
						<ActionRow
							icon={<FolderPlus className="h-3.5 w-3.5" />}
							label="New Folder"
							disabled={busy}
							onSelect={onNewFolder}
						/>
					</>
				) : null}

				{view === 'this-pc' ? (
					<>
						{loadingRepos ? (
							<p className="px-3 py-3 text-[12px] text-mute">正在扫描本机仓库…</p>
						) : filteredLocal.length === 0 ? (
							<p className="px-3 py-2 text-[12px] text-mute">
								未发现本地 Git 仓库
							</p>
						) : (
							filteredLocal.map(path => (
								<PathRow
									key={path}
									path={path}
									disabled={busy}
									onSelect={() => void openPath(path)}
								/>
							))
						)}
						<MenuSeparator />
						<ActionRow
							icon={<FolderInput className="h-3.5 w-3.5" />}
							label="Browse..."
							chevron
							disabled={busy}
							onSelect={onBrowseThisPc}
						/>
					</>
				) : null}

				{view === 'cloud' ? (
					<>
						<p className="px-3 py-1.5 text-[12px] leading-5 text-mute">
							粘贴 Git 地址，或输入 GitHub 的 owner/repo。克隆完成后会打开工作区并在右侧显示文件树。
						</p>
						<ActionRow
							icon={<Cloud className="h-3.5 w-3.5" />}
							label="Clone repository"
							disabled={busy || !expandGitUrl(query)}
							onSelect={() => void onClone()}
						/>
					</>
				) : null}
			</div>
		</div>
	);

	return createPortal(menu, document.body);
}

function SectionLabel({children}: {children: string}) {
	return (
		<div className="px-3 pt-2 pb-0.5 text-[11px] text-mute">{children}</div>
	);
}

function PathRow({
	path,
	disabled,
	onSelect,
}: {
	path: string;
	disabled?: boolean;
	onSelect: () => void;
}) {
	return (
		<button
			type="button"
			disabled={disabled}
			onClick={onSelect}
			className="xy-menu-row mx-1 flex w-[calc(100%-8px)] items-center gap-2 px-2 py-1.5 text-left text-[13px] text-ink-soft disabled:opacity-50"
		>
			<Folder className="h-3.5 w-3.5 shrink-0 text-mute" />
			<span className="min-w-0 truncate">{path}</span>
		</button>
	);
}

function ActionRow({
	icon,
	label,
	chevron,
	disabled,
	onSelect,
}: {
	icon: ReactNode;
	label: string;
	chevron?: boolean;
	disabled?: boolean;
	onSelect: () => void;
}) {
	return (
		<button
			type="button"
			disabled={disabled}
			onClick={onSelect}
			className="xy-menu-row mx-1 flex w-[calc(100%-8px)] items-center gap-2 px-2 py-1.5 text-left text-[13px] text-ink-soft disabled:cursor-default disabled:opacity-50"
		>
			<span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center text-mute">
				{icon}
			</span>
			<span className="min-w-0 flex-1 truncate">{label}</span>
			{chevron ? (
				<ChevronRight className="h-3.5 w-3.5 shrink-0 text-mute" />
			) : null}
		</button>
	);
}
