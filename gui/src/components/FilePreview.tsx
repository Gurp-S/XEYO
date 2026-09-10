import {Columns2, Maximize2, Minimize2, X} from 'lucide-react';
import {memo, useCallback, useEffect, useRef, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {CodeBlock} from '@/components/CodeBlock';
import {DiffPreview} from '@/components/DiffPreview';
import {
	EditableMarkdown,
	type EditableMarkdownHandle,
} from '@/components/EditableMarkdown';
import {PaneResizeHandle} from '@/components/PaneResizeHandle';
import {PaneSlot} from '@/components/PaneSlot';
import {SelectionToolbar} from '@/components/SelectionToolbar';
import {TextFileEditor} from '@/components/TextFileEditor';
import {showContextMenu} from '@/components/ui/ContextMenu';
import {useHoverScroll} from '@/hooks/useHoverScroll';
import {usePaneResize} from '@/hooks/usePaneResize';
import {usePresence} from '@/hooks/usePresence';
import {filePathMenuItems} from '@/lib/contextMenus';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {highlightLangForName, isMarkdownName} from '@/lib/fileKind';
import {gitFileDiff, statWorkspaceFile} from '@/lib/api';
import {applyMdFormat, type MdFormatKind} from '@/lib/mdFormat';
import {cn} from '@/lib/utils';
import {joinWorkspacePath} from '@/lib/workspaceOpen';
import {sessionStreamActive} from '@/lib/sessionStreams';
import {useChatStore} from '@/stores/chatStore';
import {useExplorerStore} from '@/stores/explorerStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {
	PANE_WIDTH_MAX,
	PANE_WIDTH_MIN,
	isSmoothnessOn,
	useSettingsStore,
} from '@/stores/settingsStore';

type PickSel = {text: string; rect: DOMRect; bound: DOMRect};
type MdMode = 'preview' | 'source';
type PreviewKind = 'diff' | 'file';

function pathParts(path: string): string[] {
	return path.split(/[\\/]/).filter(Boolean);
}

function modLabel(): string {
	return /mac/i.test(navigator.platform) ? '⌘' : 'Ctrl';
}

function firstLineRect(range: Range): DOMRect {
	const rects = range.getClientRects();
	for (const r of rects) {
		if (r.width >= 1 || r.height >= 1) {
			return r;
		}
	}
	return range.getBoundingClientRect();
}

function sameRect(a: DOMRect, b: DOMRect): boolean {
	return (
		a.left === b.left &&
		a.top === b.top &&
		a.right === b.right &&
		a.bottom === b.bottom &&
		a.width === b.width &&
		a.height === b.height
	);
}

function samePick(a: PickSel, b: PickSel): boolean {
	return a.text === b.text && sameRect(a.rect, b.rect) && sameRect(a.bound, b.bound);
}

function selectionInside(root: HTMLElement): PickSel | null {
	const sel = window.getSelection();
	if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
		return null;
	}
	const range = sel.getRangeAt(0);
	if (!root.contains(range.commonAncestorContainer)) {
		return null;
	}
	const text = sel.toString().replace(/\r\n/g, '\n');
	if (!text.trim()) {
		return null;
	}
	const rect = firstLineRect(range);
	if (rect.width < 1 && rect.height < 1) {
		return null;
	}
	return {text, rect, bound: root.getBoundingClientRect()};
}

function expandWordAtCaret(root: HTMLElement): boolean {
	const sel = window.getSelection();
	if (!sel || sel.rangeCount === 0 || !sel.isCollapsed) {
		return false;
	}
	const node = sel.anchorNode;
	if (!node || node.nodeType !== Node.TEXT_NODE || !root.contains(node)) {
		return false;
	}
	const value = node.textContent || '';
	let start = sel.anchorOffset;
	let end = sel.anchorOffset;
	const isWord = (ch: string | undefined) =>
		Boolean(ch && /[\p{L}\p{N}_]/u.test(ch));
	while (start > 0 && isWord(value[start - 1])) {
		start -= 1;
	}
	while (end < value.length && isWord(value[end])) {
		end += 1;
	}
	if (end <= start) {
		return false;
	}
	const range = document.createRange();
	range.setStart(node, start);
	range.setEnd(node, end);
	sel.removeAllRanges();
	sel.addRange(range);
	return true;
}

export const FilePreview = memo(function FilePreview() {
	const navigate = useNavigate();
	const docLive = useExplorerStore(s => s.doc);
	const loadingFile = useExplorerStore(s => s.loadingFile);
	const selectedPath = useExplorerStore(s => s.selectedPath);
	const previewExpanded = useExplorerStore(s => s.previewExpanded);
	const setPreviewExpanded = useExplorerStore(s => s.setPreviewExpanded);
	const agentBusy = useChatStore(s =>
		s.activeId ? sessionStreamActive(s, s.activeId) : false,
	);
	const closePreview = useExplorerStore(s => s.closePreview);
	const reviewDiff = useExplorerStore(s => s.reviewDiff);
	const saveFile = useExplorerStore(s => s.saveFile);
	const previewWidth = useSettingsStore(s => s.previewWidth);
	const explorerWidth = useSettingsStore(s => s.explorerWidth);
	const navHidden = useWorkspaceStore(s => s.navHidden);
	const toggleNavHidden = useWorkspaceStore(s => s.toggleNavHidden);
	const workspaceOpen = useWorkspaceStore(s => s.open);
	const collapseWorkspace = useWorkspaceStore(s => s.collapseWorkspace);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const updateSettings = useSettingsStore(s => s.update);
	const hover = useHoverScroll();
	const paneRef = useRef<HTMLElement | null>(null);
	// 工作区未展开时不显示文件预览（含聊天区链接触发的打开），收起状态下无任何工作区按钮。
	const paneOpen = Boolean(workspaceOpen && (selectedPath || loadingFile || reviewDiff));
	const holdDoc = useRef(docLive);
	if (paneOpen) {
		holdDoc.current = docLive;
	}
	const doc = paneOpen ? docLive : holdDoc.current;
	const {mounted, shown} = usePresence(paneOpen, smoothness ? 200 : 0, 0);
	const onWidth = useCallback(
		(next: number) => updateSettings({previewWidth: next}),
		[updateSettings],
	);
	// 仅在工作区打开时隐藏树导航才有意义；关闭时不扩宽、不出按钮。
	const navEff = workspaceOpen && navHidden;
	// 隐藏树导航时，文件预览占满整个工作区（自身宽度 + 工作区侧栏宽度）。
	const displayWidth = previewWidth + (navEff ? explorerWidth : 0);
	// 拖拽钳制在“槽宽域”进行：显示宽 = 基础宽 + 隐藏树宽，且不得超出
	// 聊天宿主留给功能栏的最大可用宽（保留聊天区最小列宽；见
	// .xy-pane-chat-host > main { min-width: 180px }）。否则窄窗口下把面板拖满
	// 会把聊天区顶出窗口/面板溢出视口。
	const CHAT_COL_MIN = 180;
	const slotOf = useCallback(
		(base: number) => base + (navEff ? explorerWidth : 0),
		[navEff, explorerWidth],
	);
	const slotMax = useCallback(() => {
		const host = document.querySelector<HTMLElement>('.xy-pane-chat-host');
		const avail = host
			? host.clientWidth
			: document.querySelector<HTMLElement>('.xy-pane-row')?.clientWidth ??
				PANE_WIDTH_MAX + PANE_WIDTH_MAX;
		return Math.max(PANE_WIDTH_MIN, avail - CHAT_COL_MIN - 2);
	}, []);
	const {dragging, onResizeStart} = usePaneResize(
		previewWidth,
		onWidth,
		PANE_WIDTH_MIN,
		PANE_WIDTH_MAX,
		{invert: true, paneRef, slotOf, slotMax},
	);
	const previewWidthShown = Math.min(displayWidth, slotMax());
	// 功能界面切换（工具面板 ↔ 文件预览）时硬切，不播滑动动画。
	const toolOn = useWorkspaceStore(s => s.activeTool !== null);
	const toolOnRef = useRef(toolOn);
	const hardSwitch = toolOn !== toolOnRef.current;
	toolOnRef.current = toolOn;
	const [mdMode, setMdMode] = useState<MdMode>('preview');
	const [previewKind, setPreviewKind] = useState<PreviewKind>('file');
	const [draft, setDraft] = useState('');
	const [dirty, setDirty] = useState(false);
	const [saving, setSaving] = useState(false);
	const [jumpHash, setJumpHash] = useState<string | null>(null);
	const [pick, setPick] = useState<PickSel | null>(null);
	const [mdRevision, setMdRevision] = useState(0);
	const pendingPath = useRef<string | null>(null);
	const bodyRef = useRef<HTMLDivElement | null>(null);
	const mdEditRef = useRef<EditableMarkdownHandle | null>(null);
	const pickRef = useRef<PickSel | null>(null);
	const pickVersionRef = useRef(0);
	const dirtyRef = useRef(false);
	const lastSaved = useRef('');
	const draftRef = useRef('');
	const draftPathRef = useRef<string | null>(null);
	const knownStat = useRef<{path: string; mtime: number; size: number} | null>(
		null,
	);
	const scrollTopRef = useRef(0);
	const liveDiffEpoch = useRef(0);
	pickRef.current = pick;
	dirtyRef.current = dirty;
	draftRef.current = draft;

	const openFile = useExplorerStore(s => s.openFile);
	const onOpenPath = useCallback(
		(path: string, hash?: string) => {
			pendingPath.current = path;
			setJumpHash(hash ?? null);
			void openFile(path);
		},
		[openFile],
	);

	const setBodyRef = useCallback(
		(el: HTMLDivElement | null) => {
			pickVersionRef.current += 1;
			bodyRef.current = el;
			hover.scrollerRef(el);
		},
		[hover.scrollerRef],
	);

	// 无会话审查时，从后端取工作区当前 vs HEAD 的 diff（覆盖真实改动浏览）。
	const [liveDiff, setLiveDiff] = useState<string | null>(null);
	const reviewCoversFile = Boolean(
		reviewDiff?.path === selectedPath && reviewDiff?.diff,
	);

	const refreshLiveDiff = useCallback((path: string) => {
		liveDiffEpoch.current += 1;
		const epoch = liveDiffEpoch.current;
		void gitFileDiff(path)
			.then(result => {
				if (epoch !== liveDiffEpoch.current) {
					return;
				}
				if (result.kind === 'diff' || result.kind === 'untracked') {
					setLiveDiff(result.diff ?? '');
				} else {
					setLiveDiff(null);
				}
			})
			.catch(() => {
				if (epoch === liveDiffEpoch.current) {
					setLiveDiff(null);
				}
			});
	}, []);

	// 换路径或 Agent 写盘导致 doc 指纹变化时刷新「改动」页。
	const docStamp = doc
		? `${doc.path}:${doc.mtime ?? ''}:${doc.size}:${doc.kind}`
		: '';
	useEffect(() => {
		if (!selectedPath || reviewCoversFile) {
			setLiveDiff(null);
			return;
		}
		refreshLiveDiff(selectedPath);
	}, [selectedPath, reviewCoversFile, refreshLiveDiff, docStamp]);

	const markdown = Boolean(doc && isMarkdownName(doc.name));
	const truncated = Boolean(doc?.truncated);
	const editable = Boolean(doc?.kind === 'text' && doc.text != null && !truncated);
	const hasReview = reviewCoversFile;
	const diffText = hasReview && reviewDiff ? reviewDiff.diff : liveDiff;
	const showDiff = Boolean(diffText && previewKind === 'diff');
	const showMdPreview = Boolean(!showDiff && markdown && mdMode === 'preview');
	const showCodeView = Boolean(
		!showDiff &&
			doc?.kind === 'text' &&
			!truncated &&
			!markdown &&
			mdMode === 'preview',
	);
	const showPreview = showMdPreview;
	const showEditor = Boolean(!showDiff && editable && mdMode === 'source');
	const snippetName = doc?.name || 'selection';
	const snippetPath = doc?.path || selectedPath || snippetName;

	useEffect(() => {
		if (reviewDiff?.path === selectedPath && reviewDiff.diff) {
			setPreviewKind('diff');
			return;
		}
		setPreviewKind('file');
	}, [reviewDiff, selectedPath]);

	useEffect(() => {
		if (!selectedPath) {
			return;
		}
		setPick(null);
		setDirty(false);
		dirtyRef.current = false;
		setDraft('');
		lastSaved.current = '';
		draftRef.current = '';
		draftPathRef.current = selectedPath;
		knownStat.current = null;
		// 默认高亮（preview）：markdown 为“预览”，代码文件为“高亮”；
		// 文件首次打开直接呈现语法高亮，点“编辑”切换回源码编辑器。
		setMdMode('preview');
		if (pendingPath.current && pendingPath.current === selectedPath) {
			pendingPath.current = null;
			return;
		}
		pendingPath.current = null;
		setJumpHash(null);
		setMdRevision(0);
		pickVersionRef.current += 1;
		setPick(null);
		setDirty(false);
	}, [selectedPath]);

	useEffect(() => {
		if (!doc || doc.kind !== 'text' || doc.path !== selectedPath) {
			return;
		}
		if (dirtyRef.current) {
			return;
		}
		const text = doc.text ?? '';
		if (text === draftRef.current) {
			return;
		}
		// 外部刷新（Agent 写盘）时尽量保住滚动位置。
		const scroller = bodyRef.current;
		if (scroller) {
			scrollTopRef.current = scroller.scrollTop;
		}
		setDraft(text);
		lastSaved.current = text;
		draftRef.current = text;
		if (doc.mtime != null) {
			knownStat.current = {
				path: selectedPath ?? doc.path,
				mtime: doc.mtime,
				size: doc.size,
			};
		}
		requestAnimationFrame(() => {
			const el = bodyRef.current;
			if (el && scrollTopRef.current > 0) {
				el.scrollTop = scrollTopRef.current;
			}
		});
	}, [doc, selectedPath]);

	// 同步 doc 的 mtime/size 到 knownStat（含图片/二进制）。
	useEffect(() => {
		if (!doc || !selectedPath) {
			return;
		}
		if (doc.mtime != null) {
			knownStat.current = {
				path: selectedPath,
				mtime: doc.mtime,
				size: doc.size,
			};
		}
	}, [doc, selectedPath]);

	// Tool 事件通常会主动触发 reloadIfOpen；忙碌期只轮询 mtime/size，变化才整文件读。
	// 有未保存修改时不覆盖草稿。空闲下降沿再 stat 一次，避免最后一次 Write 漏刷。
	useEffect(() => {
		if (!selectedPath || !paneOpen) {
			return;
		}
		let active = true;
		const checkStat = async () => {
			if (!active || dirtyRef.current) {
				return;
			}
			try {
				const st = await statWorkspaceFile(selectedPath);
				if (!active) {
					return;
				}
				const prev = knownStat.current;
				if (
					prev &&
					prev.path === selectedPath &&
					prev.mtime === st.mtime &&
					prev.size === st.size
				) {
					return;
				}
				knownStat.current = {
					path: selectedPath,
					mtime: st.mtime,
					size: st.size,
				};
				const changed = await useExplorerStore
					.getState()
					.reloadIfOpen(selectedPath);
				if (changed && !reviewCoversFile) {
					refreshLiveDiff(selectedPath);
				}
			} catch {
				/* 预览保持现状 */
			}
		};
		void checkStat();
		if (!agentBusy) {
			return () => {
				active = false;
			};
		}
		const timer = window.setInterval(() => {
			void checkStat();
		}, 700);
		return () => {
			active = false;
			window.clearInterval(timer);
		};
	}, [agentBusy, selectedPath, paneOpen, reviewCoversFile, refreshLiveDiff]);

	// Escape 退出放大（与 Mermaid 全屏同一 escStack）。
	useEffect(() => {
		if (!previewExpanded || !paneOpen) {
			return;
		}
		pushEscLayer('file-preview-expand', () => setPreviewExpanded(false));
		return () => popEscLayer('file-preview-expand');
	}, [previewExpanded, paneOpen, setPreviewExpanded]);

	const persist = useCallback(
		async (text: string) => {
			const path = selectedPath;
			if (!path || truncated || text === lastSaved.current) {
				return;
			}
			setSaving(true);
			try {
				await saveFile(path, text);
				lastSaved.current = text;
				setDirty(false);
				dirtyRef.current = false;
			} catch (err) {
				// 403 通常是 workspace_fs 直写通道未开启（默认关闭，属安全默认值）。
				// 给出可执行的说明，而不是把后端原文直接抛给用户。
				const msg = err instanceof Error ? err.message : String(err);
				window.alert(
					msg.includes('XEYO_WORKSPACE_FS_WRITABLE')
						? '当前未开启编辑器直写保存。如需在预览面板直接保存文件，' +
								'请设置环境变量 XEYO_WORKSPACE_FS_WRITABLE=1 后重启应用；' +
								'也可以让 XEYO 代为修改该文件（走引擎权限与回滚链）。'
						: msg,
				);
			} finally {
				setSaving(false);
			}
		},
		[saveFile, selectedPath, truncated],
	);

	useEffect(() => {
		if (!dirty || truncated) {
			return;
		}
		const t = window.setTimeout(() => {
			void persist(draftRef.current);
		}, 700);
		return () => window.clearTimeout(t);
	}, [draft, dirty, persist, truncated]);

	useEffect(() => {
		const path = selectedPath;
		const persistForPath = persist;
		return () => {
			if (!path || !dirtyRef.current || draftPathRef.current !== path) {
				return;
			}
			mdEditRef.current?.flush();
			dirtyRef.current = false;
			void persistForPath(draftRef.current);
		};
	}, [selectedPath, persist]);

	const onDraftChange = useCallback((next: string) => {
		setDraft(next);
		draftRef.current = next;
		setDirty(next !== lastSaved.current);
		dirtyRef.current = next !== lastSaved.current;
	}, []);

	const refreshPick = useCallback(() => {
		const root = bodyRef.current;
		if (!root) {
			setPick(null);
			return;
		}
		const next = selectionInside(root);
		setPick(prev => {
			if (prev && next && samePick(prev, next)) {
				return prev;
			}
			return next;
		});
	}, []);

	const addToChat = useCallback(
		(text: string) => {
			useChatStore.getState().requestComposerInsert({
				name: snippetName,
				text: `From \`${snippetPath}\`:\n\n${text}`,
			});
			setPick(null);
		},
		[snippetName, snippetPath],
	);

	const addToSide = useCallback(
		async (text: string) => {
			const id = await useChatStore.getState().createSession();
			useChatStore.getState().requestComposerInsert({
				name: snippetName,
				text: `From \`${snippetPath}\`:\n\n${text}`,
			});
			navigate(`/c/${id}`);
			setPick(null);
		},
		[navigate, snippetName, snippetPath],
	);

	useEffect(() => {
		const schedulePickRefresh = () => {
			const version = pickVersionRef.current;
			window.requestAnimationFrame(() => {
				if (pickVersionRef.current === version) {
					refreshPick();
				}
			});
		};
		const onMouseUp = (e: MouseEvent) => {
			const root = bodyRef.current;
			if (!root) {
				return;
			}
			if (e.button !== 0) {
				return;
			}
			if (!root.contains(e.target as Node)) {
				if (!(e.target as HTMLElement | null)?.closest?.('[role="toolbar"]')) {
					setPick(null);
				}
				return;
			}
			if (
				showPreview &&
				!(e.target as HTMLElement).closest(
					'a, button, textarea, [contenteditable="true"]',
				)
			) {
				expandWordAtCaret(root);
			}
			schedulePickRefresh();
		};
		const onKey = (e: KeyboardEvent) => {
			if (e.key === 'Escape') {
				setPick(null);
			}
			if (
				e.shiftKey &&
				(e.key.startsWith('Arrow') || e.key === 'Home' || e.key === 'End')
			) {
				schedulePickRefresh();
			}
			const add =
				e.key.toLowerCase() === 'l' && (e.ctrlKey || e.metaKey) && !e.shiftKey;
			if (!add) {
				return;
			}
			const cur = pickRef.current;
			if (!cur) {
				return;
			}
			e.preventDefault();
			addToChat(cur.text);
		};
		const onScroll = () => {
			if (pickRef.current) {
				refreshPick();
			}
		};
		const root = bodyRef.current;
		document.addEventListener('mouseup', onMouseUp);
		window.addEventListener('keydown', onKey);
		root?.addEventListener('scroll', onScroll, {passive: true});
		return () => {
			document.removeEventListener('mouseup', onMouseUp);
			window.removeEventListener('keydown', onKey);
			root?.removeEventListener('scroll', onScroll);
		};
	}, [addToChat, refreshPick, showPreview]);

	const onFormat = useCallback(
		(kind: MdFormatKind) => {
			const cur = pickRef.current;
			const path = doc?.path;
			if (!cur || !path) {
				return;
			}
			if (truncated) {
				window.alert('文件过长，无法在预览里直接编辑。');
				return;
			}
			let href: string | undefined;
			if (kind === 'link') {
				const next = window.prompt('链接地址', 'https://');
				if (next == null) {
					return;
				}
				href = next;
			}
			const fromPreview = mdEditRef.current?.flush() ?? draftRef.current;
			const next = applyMdFormat(fromPreview, cur.text, kind, href);
			if (!next) {
				window.alert('选区无法对应到 Markdown 源码，请改用源码视图再试。');
				return;
			}
			onDraftChange(next);
			setMdRevision(n => n + 1);
			void persist(next);
			window.getSelection()?.removeAllRanges();
			setPick(null);
		},
		[doc, onDraftChange, persist, truncated],
	);

	if (!smoothness && !mounted) {
		return null;
	}

	const name =
		doc?.name ||
		reviewDiff?.name ||
		selectedPath?.split(/[\\/]/).pop() ||
		'文件';
	const crumbs = pathParts(doc?.path || selectedPath || reviewDiff?.path || '');
	const showMdTools = markdown && showPreview;
	const saveHint = truncated
		? '文件过长，只读'
		: saving
			? '保存中…'
			: dirty
				? '未保存'
				: '已保存';

	const headerBar = (
		<div className="flex h-10 shrink-0 items-center justify-between gap-2 px-2">
			<div
				className="min-w-0 truncate px-1 text-[12px] text-mute"
				onContextMenu={event => {
					const entryPath =
						doc?.path || selectedPath || reviewDiff?.path || '';
					if (!entryPath) {
						return;
					}
					const root =
						useChatStore.getState().spaces.find(
							sp => sp.id === useChatStore.getState().activeSpaceId,
						)?.rootPath ?? '';
					const absolutePath = joinWorkspacePath(root, entryPath);
					showContextMenu(
						event,
						filePathMenuItems({
							entryPath,
							entryName: name,
							absolutePath,
							kind: 'file',
							onOpen: () =>
								void useExplorerStore.getState().openFile(entryPath),
							onOpenReview: reviewDiff
								? () =>
										void useExplorerStore.getState().openReview({
											path: reviewDiff.path,
											name: reviewDiff.name,
											diff: reviewDiff.diff,
										})
								: undefined,
						}),
						`${name} 文件`,
					);
				}}
			>
				{crumbs.length > 1 ? (
					<>
						{crumbs.slice(0, -1).map((part, i) => (
							<span key={`${part}-${i}`}>
								{part}
								<span className="px-1 text-mute/50">›</span>
							</span>
						))}
						<span className="text-ink-soft">{crumbs[crumbs.length - 1]}</span>
					</>
				) : (
					<span className="text-ink-soft">{name}</span>
				)}
				<span className="ml-2 text-[10px] text-mute">{saveHint}</span>
			</div>
			<div className="flex shrink-0 items-center gap-0.5">
				{hasReview || liveDiff ? (
					<button
						type="button"
						className={cn(
							'rounded-md px-2 py-1 text-[11px] text-mute hover:bg-glass-hover hover:text-ink',
							previewKind === 'diff' && 'bg-glass-hover text-ink',
						)}
						onClick={() =>
							setPreviewKind(kind => (kind === 'diff' ? 'file' : 'diff'))
						}
					>
						{previewKind === 'diff' ? '文件' : '改动'}
					</button>
				) : null}
				{editable && !showDiff ? (
					<>
						{(
							[
								['preview', markdown ? '预览' : '高亮'],
								['source', markdown ? '源码' : '编辑'],
							] as const
						).map(([id, label]) => (
							<button
								key={id}
								type="button"
								className={cn(
									'rounded-md px-2 py-1 text-[11px] text-mute hover:bg-glass-hover hover:text-ink',
									previewKind === 'file' &&
										mdMode === id &&
										'bg-glass-hover text-ink',
								)}
								onClick={() => {
									if (id === 'source') {
										mdEditRef.current?.flush();
									}
									setPreviewKind('file');
									setMdMode(id);
								}}
							>
								{label}
							</button>
						))}
					</>
				) : null}
				{navEff && !previewExpanded ? (
					<button
						type="button"
						className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
						aria-label="展开右边内容"
						title="展开右边内容"
						onClick={toggleNavHidden}
					>
						<Columns2 className="h-3.5 w-3.5" />
					</button>
				) : null}
				<button
					type="button"
					className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
					aria-label={previewExpanded ? '还原预览' : '放大预览'}
					title={previewExpanded ? '还原预览' : '放大预览'}
					onClick={() => setPreviewExpanded(!previewExpanded)}
				>
					{previewExpanded ? (
						<Minimize2 className="h-3.5 w-3.5" />
					) : (
						<Maximize2 className="h-3.5 w-3.5" />
					)}
				</button>
				<button
					type="button"
					className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
					aria-label="关闭预览"
					onClick={() => {
						mdEditRef.current?.flush();
						dirtyRef.current = false;
						void persist(draftRef.current);
						closePreview();
						// 只剩文件预览（树导航已收起）时，关闭直接收起整个工作区。
						if (navEff) {
							collapseWorkspace();
						}
					}}
				>
					<X className="h-3.5 w-3.5" />
				</button>
			</div>
		</div>
	);

	const body = (
		<>
			<div
				key={doc?.path || selectedPath || 'empty'}
				className="flex min-h-0 flex-1 flex-col"
			>
				{loadingFile && !showDiff ? (
					<p className="px-5 py-4 text-[13px] text-mute">正在打开…</p>
				) : null}
				{!loadingFile && !doc && !showDiff ? (
					<div className="flex h-full flex-col items-center justify-center gap-3 text-mute">
						<p className="text-[14px]">打开一个文件开始查看</p>
					</div>
				) : null}
				{showDiff && diffText ? (
					<div
						ref={setBodyRef}
						className="flex min-h-0 flex-1 flex-col"
						onMouseEnter={hover.onMouseEnter}
						onMouseLeave={hover.onMouseLeave}
					>
						<DiffPreview
							diff={diffText}
							fill
							className="xy-hover-scroll"
						/>
					</div>
				) : null}
				{!showDiff && doc?.kind === 'image' && doc.data_url ? (
					<div className="xy-hover-scroll min-h-0 flex-1 overflow-auto px-5 py-4">
						<img
							src={doc.data_url}
							alt={doc.name}
							className="mx-auto max-h-full max-w-full rounded-lg border border-line/50"
						/>
					</div>
				) : null}
				{!showDiff && doc?.kind === 'binary' ? (
					<p className="px-5 py-4 font-mono text-[13px] text-mute">{doc.text}</p>
				) : null}
				{!showDiff && doc?.kind === 'text' && truncated ? (
					<div
						ref={setBodyRef}
						className="xy-hover-scroll min-h-0 flex-1 overflow-auto px-0 py-0"
					>
						<p className="px-3 py-2 text-[11px] text-mute">
							文件超过预览上限，已截断为只读。
						</p>
						<CodeBlock
							language={highlightLangForName(doc.name)}
							value={doc.text ?? ''}
							autoCollapse={false}
							variant="file"
						/>
					</div>
				) : null}
				{doc?.kind === 'text' && !truncated && showEditor ? (
					<div className="flex min-h-0 flex-1 flex-col">
						<TextFileEditor
							value={draft}
							onChange={onDraftChange}
							onSave={() => void persist(draft)}
							aria-label={`${name} 源码`}
						/>
					</div>
				) : null}
				{doc?.kind === 'text' && !truncated && showCodeView ? (
					<CodeBlock
						language={highlightLangForName(doc.name)}
						value={draft}
						autoCollapse={false}
						variant="file"
					/>
				) : null}
				{doc?.kind === 'text' && !truncated && showPreview ? (
					<div
						ref={setBodyRef}
						className="xy-hover-scroll min-h-0 min-w-0 flex-1 overflow-auto px-5 py-4"
					>
						<EditableMarkdown
							ref={mdEditRef}
							content={draft}
							onChange={onDraftChange}
							onSave={() => void persist(draftRef.current)}
							codeAutoCollapse
							className="xy-md-doc w-full min-w-0 max-w-3xl"
							basePath={doc.path}
							scrollToId={jumpHash}
							onOpenPath={onOpenPath}
							revision={mdRevision}
						/>
					</div>
				) : null}
			</div>
			{pick && showPreview ? (
				<SelectionToolbar
					variant={showMdTools ? 'markdown' : 'code'}
					rect={pick.rect}
					bound={pick.bound}
					modLabel={modLabel()}
					onAskAgent={() => addToChat(pick.text)}
					onAskSide={() => void addToSide(pick.text)}
					onFormat={showMdTools ? onFormat : undefined}
				/>
			) : null}
		</>
	);

	// 放大：覆盖聊天列宿主（absolute inset-0），聊天保持挂载；无宽度过渡。
	if (previewExpanded && (paneOpen || mounted)) {
		return (
			<section
				ref={paneRef as never}
				className={cn(
					'absolute inset-0 z-20 flex min-h-0 min-w-0 flex-col overflow-hidden',
					'xy-workspace-chrome bg-paper',
				)}
				aria-label="文件预览（放大）"
				onMouseEnter={hover.onMouseEnter}
				onMouseLeave={hover.onMouseLeave}
			>
				{headerBar}
				{body}
			</section>
		);
	}

	return (
		<PaneSlot
			as="section"
			open={paneOpen}
			mounted={mounted}
			shown={shown}
			width={previewWidthShown}
			smoothness={smoothness}
			dragging={dragging}
			side="right"
			paneRef={paneRef}
			instant={hardSwitch}
			className={cn(
				'xy-workspace-chrome bg-transparent',
				!paneOpen && 'pointer-events-none',
			)}
			onMouseEnter={hover.onMouseEnter}
			onMouseLeave={hover.onMouseLeave}
		>
			{paneOpen || mounted ? (
				<PaneResizeHandle
					edge="left"
					dragging={dragging}
					label="拖动调整预览栏宽度"
					onMouseDown={onResizeStart}
				/>
			) : null}
			{headerBar}
			{body}
		</PaneSlot>
	);
});
