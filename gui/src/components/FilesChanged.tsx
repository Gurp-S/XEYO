import {Ellipsis} from 'lucide-react';
import {memo, useState, type MouseEvent as ReactMouseEvent} from 'react';
import {gitFileDiff} from '@/lib/api';
import {showContextMenu} from '@/components/ui/ContextMenu';
import {filePathMenuItems} from '@/lib/contextMenus';
import {useIconTheme} from '@/lib/iconThemeLoader';
import {joinWorkspacePath} from '@/lib/workspaceOpen';
import type {ChangedFile} from '@/lib/toolActivity';
import {cn} from '@/lib/utils';
import {samePath} from '@/lib/paths';
import {toast} from '@/lib/toast';
import {useChatStore} from '@/stores/chatStore';
import {useExplorerStore} from '@/stores/explorerStore';

const PREVIEW = 6;

function FileKindIcon({name}: {name: string}) {
	const mod = useIconTheme();
	if (!mod) {
		return null;
	}
	const ext = name.includes('.')
		? (name.split('.').pop()?.toLowerCase() ?? '')
		: '';
	const icon = mod.getFileIcon({
		fileExtension: ext || undefined,
		fileName: name,
		fallback: 'file',
	});
	return <mod.MaterialIcon name={icon} size={14} />;
}

type Props = {
	files: ChangedFile[];
};

/**
 * 读到回执、但那一栏没有文本差异可显示时的说明。
 * 空面板本身不说话，用户只会看到"这个改动没有内容" —— 那与"这是二进制文件"
 * 或"工作区不是仓库"是三件不同的事，必须分开说。
 */
export function reviewGapNote(kind: string | undefined, hasText: boolean): string {
	if (hasText) {
		return '';
	}
	switch (kind) {
		case 'binary':
			return '这是二进制文件，没有文本差异可显示。';
		case 'unchanged':
			return '这个文件相对 HEAD 没有文本差异（列表里的改动可能已被提交，或已被后续写入覆盖）。';
		case 'none':
			return '当前工作区不是 Git 仓库，读不出这个文件的差异。';
		default:
			return '';
	}
}

export async function openChangedReview(f: ChangedFile): Promise<void> {
	const initialState = useChatStore.getState();
	const root = initialState.spaces.find(space => space.id === initialState.activeSpaceId)?.rootPath?.trim() ?? '';
	let diff = f.diff ?? '';
	if (!diff.trim() && root) {
		let kind: string | undefined;
		try {
			const res = await gitFileDiff(f.path, root);
			const currentState = useChatStore.getState();
			const currentRoot = currentState.spaces.find(space => space.id === currentState.activeSpaceId)?.rootPath?.trim() ?? '';
			if (!samePath(root, currentRoot)) return;
			diff = typeof res.diff === 'string' ? res.diff : '';
			kind = res.kind;
		} catch (err) {
			// 读不出不开空面板：过去这里把 diff 置空后照常 openReview，
			// 界面就显示成"这个改动没有内容"。
			void toast.error(
				`读不出 ${f.name} 的差异：${err instanceof Error ? err.message : String(err)}`,
			);
			return;
		}
		const note = reviewGapNote(kind, diff.trim() !== '');
		if (note) {
			void toast.info(note);
			return;
		}
	}
	const currentState = useChatStore.getState();
	const currentRoot = currentState.spaces.find(space => space.id === currentState.activeSpaceId)?.rootPath?.trim() ?? '';
	if (!samePath(root, currentRoot)) return;
	void useExplorerStore.getState().openReview({
		path: f.path,
		name: f.name,
		diff,
	});
}

/**
 * Changes 面板：带 +/− 与 new 标记的文件行；
 * 点击文件行直接打开右侧完整 diff 面板（复用 openReview）。
 */
function FilesChangedInner({files}: Props) {
	const [showAll, setShowAll] = useState(false);

	if (files.length === 0) {
		return null;
	}

	const visible = showAll ? files : files.slice(0, PREVIEW);
	const more = files.length - PREVIEW;
	const totalAdd = files.reduce((n, f) => n + f.add, 0);
	const totalDel = files.reduce((n, f) => n + f.del, 0);

	return (
		<div className="xy-panel-ask xy-panel-ask-card anim-rise mt-2.5">
			<div className="xy-panel-ask-head">
				<span className="xy-panel-ask-title">文件变更</span>
				<span className="xy-panel-ask-count">
					{files.length} 个文件
					{totalAdd > 0 || totalDel > 0
						? ` · ${totalAdd > 0 ? `+${totalAdd}` : ''}${totalDel > 0 ? `-${totalDel}` : ''}`
						: ''}
				</span>
			</div>
			<div className="xy-panel-ask-body xy-panel-ask-files">
				<ul>
					{visible.map(f => {
						return (
							<li key={f.path}>
								<button
									type="button"
									title={f.path}
									onClick={() => {
										void openChangedReview(f);
									}}
									onContextMenu={(event: ReactMouseEvent) => {
										const root =
											useChatStore.getState().spaces.find(
												sp =>
													sp.id ===
													useChatStore.getState().activeSpaceId,
											)?.rootPath ?? '';
										const absolutePath = joinWorkspacePath(root, f.path);
										showContextMenu(
											event,
											filePathMenuItems({
												entryPath: f.path,
												entryName: f.name,
												absolutePath,
												kind: 'file',
												onOpen: () =>
													void useExplorerStore.getState().openFile(f.path),
												onOpenReview: () => void openChangedReview(f),
												includeSaveAs: false,
											}),
											`${f.name} 变更`,
										);
									}}
									className={cn(
										'xy-panel-ask-file-row',
										'hover:bg-glass-hover/60',
									)}
								>
									<span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
										<FileKindIcon name={f.name} />
									</span>
									<span className="min-w-0 flex-1 truncate font-sans text-[12px] leading-none text-ink-soft">
										{f.name}
									</span>
									{f.created ? (
										<span className="shrink-0 rounded bg-ok/15 px-1 py-0.5 font-sans text-[10px] leading-none text-ok">
											new
										</span>
									) : null}
									<span className="flex shrink-0 items-center gap-1 font-mono text-[10px] leading-none tabular-nums">
										{f.add > 0 ? (
											<span className="text-ok">+{f.add}</span>
										) : null}
										{f.del > 0 ? (
											<span className="text-danger">-{f.del}</span>
										) : null}
										{f.add === 0 && f.del === 0 ? (
											<span className="text-mute/70">—</span>
										) : null}
									</span>
								</button>
							</li>
						);
					})}
					{!showAll && more > 0 ? (
						<li>
							<button
								type="button"
								onClick={() => setShowAll(true)}
								className="xy-panel-ask-file-row font-sans text-[11px] leading-none text-mute hover:text-ink-soft"
							>
								<Ellipsis
									className="h-3.5 w-3.5 shrink-0 opacity-70"
									strokeWidth={1.5}
									aria-hidden
								/>
								显示其余 {more} 个文件
							</button>
						</li>
					) : null}
				</ul>
			</div>
		</div>
	);
}

export const FilesChanged = memo(FilesChangedInner);
