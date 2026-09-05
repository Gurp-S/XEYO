import {Ellipsis} from 'lucide-react';
import {memo, useState, type MouseEvent as ReactMouseEvent} from 'react';
import {gitFileDiff} from '@/lib/api';
import {showContextMenu} from '@/components/ui/ContextMenu';
import {filePathMenuItems} from '@/lib/contextMenus';
import {useIconTheme} from '@/lib/iconThemeLoader';
import {joinWorkspacePath} from '@/lib/workspaceOpen';
import type {ChangedFile} from '@/lib/toolActivity';
import {cn} from '@/lib/utils';
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

async function openChangedReview(f: ChangedFile): Promise<void> {
	let diff = f.diff ?? '';
	if (!diff.trim()) {
		try {
			const res = await gitFileDiff(f.path);
			diff = String(res.diff ?? '');
		} catch {
			diff = '';
		}
	}
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
				<span className="xy-panel-ask-title">Changes</span>
				<span className="xy-panel-ask-count">
					{files.length} file{files.length === 1 ? '' : 's'}
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
								Show {more} more
							</button>
						</li>
					) : null}
				</ul>
			</div>
		</div>
	);
}

export const FilesChanged = memo(FilesChangedInner);
