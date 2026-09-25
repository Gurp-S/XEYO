import {
	ArrowUp,
	ChevronDown,
	GripVertical,
	Network,
	Pencil,
	Plus,
	Send,
	Square,
	X,
} from 'lucide-react';
import {
	useEffect,
	useId,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
	type ClipboardEvent,
	type CSSProperties,
	type KeyboardEvent,
	type MouseEvent as ReactMouseEvent,
} from 'react';
import {fetchFileReferences, uploadFile, uploadMedia, resumeInbox, type SkillInfo} from '@/lib/api';
import {
	canEditInboxItem,
	canManuallyResumeInbox,
	canMutateInboxItem,
	prioritizeInboxPreview,
} from '@/lib/inboxItemState';
import {
	currentFileReferenceResult,
	fileReferenceQueryKey,
	type FileReferenceQueryResult,
} from '@/lib/fileReferenceQuery';
import {createTaAutoResize} from '@/lib/taAutoResize';
import {TypingCaret, type CaretColorRange, type TypingCaretApi} from '@/components/composer/TypingCaret';
import {
	activeBackendSessionId,
	type InboxQueuedItem,
} from '@/stores/chat/preStoreHelpers';
import {
	defaultComposerDraft,
	getComposerDraft,
	patchComposerDraftModes,
	setComposerDraft,
	type DraftAttachment,
	type DraftFileAttachment,
	type DraftImageAttachment,
} from '@/lib/composerDrafts';
import {selectActiveSessionStream, sessionStreamActive} from '@/lib/sessionStreams';
import {
	slashGhostHint,
	slashLeadingColor,
	slashSuggestions,
	slashTokenAt,
	triggerTokenAt,
} from '@/lib/slash';
import {arbitrateSlashMenuKey, type SlashMenuKey} from '@/lib/slashMenuKeys';
import {resolveSendMode, steerHintVisible, type SendMode} from '@/lib/composerSendMode';
import {
	cachedSlashSkills,
	handleComposerSlash,
	lastUserMessage,
	loadSlashSkills,
} from '@/lib/slashCommands';
import {newSession} from '@/lib/appNav';
import {useHasComposerPendingDock} from '@/hooks/usePendingForActiveSession';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {textFieldMenuItems} from '@/lib/contextMenus';
import {toast} from '@/lib/toast';
import {cn, uid} from '@/lib/utils';
import {allowsEmptyApiKey} from '@/lib/localTestGate';
import {isSmoothnessOn, useSettingsStore, type ReasoningEffort} from '@/stores/settingsStore';
import {useChatUiStore, useChatUiStoreApi} from '@/stores/chatUiStore';
import {useChatStore} from '@/stores/chatStore';
import {useRemoteStore} from '@/stores/remoteStore';
import {ModelPicker} from '@/components/ModelPicker';
import {showContextMenu} from '@/components/ui/ContextMenu';
import {ZoomIn} from 'lucide-react';
import {ApprovalModeButton} from './ApprovalModeButton';
import {ModeChip} from './ModeChip';
import {PermissionDialog} from './PermissionDialog';
import {AskUserDialog} from './AskUserDialog';
import {PlanDialog} from './PlanDialog';
import {ErrorBanner} from './ErrorBanner';
import {SessionTodoDock, useSessionTodoDockLive} from './SessionTodoDock';
import {ComposerQuickMenu} from './ComposerQuickMenu';
import {McpPanel} from './McpPanel';
import {SessionGoalDock, useSessionGoalDockLive} from './SessionGoalDock';
import {ImageReaderDialog} from './ImageReader';
import {normalizeAgentMode} from '@/lib/agentMode';
import {SIDE_SPACE_ID} from '@/lib/db';

type FileAttachment = DraftFileAttachment;
type ImageAttachment = DraftImageAttachment;
type Attachment = DraftAttachment;
const EMPTY_SLASH_SKILLS: SkillInfo[] = [];

function removeSubmittedAttachments(current: Attachment[], submitted: Attachment[]) {
	const submittedIds = new Set(submitted.map(attachment => attachment.id));
	const removed = current.filter(attachment => submittedIds.has(attachment.id));
	return {
		removed,
		remaining: current.filter(attachment => !submittedIds.has(attachment.id)),
	};
}

const MAX_IMAGES = 8;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
/** 排队卡默认展示条数：超出折叠为「展开其余 N 条」。 */
const QUEUE_PREVIEW_COUNT = 3;
/** 空态单行高度（矮框）；输入变多后长到 TA_MAX；封顶后内部滚动 */
const TA_MIN_PX = 36;
const TA_MAX_PX = 120;
const TA_EXPANDED_HEIGHT = 'min(58vh, 440px)';

function SendStopButton({
	streaming,
	canSend,
	smoothness,
	onSend,
	onStop,
}: {
	streaming: boolean;
	canSend: boolean;
	smoothness: boolean;
	onSend: () => void;
	onStop: () => void;
}) {
	// P1：忙碌且有输入时按钮仍可发送（后端 202 排队）；仅「忙碌且无输入」显示停止。
	const showStop = streaming && !canSend;
	if (!smoothness) {
		if (showStop) {
			return (
				<button
					type="button"
											onClick={onStop}
						aria-label="停止生成"
						title="停止生成"
						className="xy-press flex h-8 w-8 items-center justify-center rounded-full bg-ink text-paper hover:bg-ink-soft"
						
				>
					<Square className="h-3 w-3 fill-current" />
				</button>
			);
		}
		return (
			<button
				type="button"
					onClick={() => onSend()}
aria-label="发送"
									title="发送"
									disabled={!canSend}
				className={cn(
					'flex h-8 w-8 items-center justify-center rounded-full transition-colors',
					canSend
						? 'bg-accent text-on-accent hover:bg-accent-hover'
						: 'cursor-not-allowed bg-paper-deep text-mute',
				)}
				
			>
				<ArrowUp className="h-4 w-4" strokeWidth={2.25} />
			</button>
		);
	}
	return (
		<button
			type="button"
			onClick={showStop ? onStop : () => onSend()}
			disabled={!streaming && !canSend}
			className={cn(
				'xy-press relative flex h-8 w-8 items-center justify-center rounded-full',
				showStop
					? 'bg-ink text-paper hover:bg-ink-soft'
					: canSend
						? 'bg-accent text-on-accent hover:bg-accent-hover'
						: 'cursor-not-allowed bg-paper-deep text-mute',
			)}
			
			aria-label={showStop ? '停止生成' : '发送'}
				title={showStop ? '停止生成' : '发送'}
		>
			<ArrowUp
				className={cn(
					'xy-send-stop-icon absolute h-4 w-4',
					showStop ? 'scale-90 opacity-0' : 'scale-100 opacity-100',
				)}
				strokeWidth={2.25}
				aria-hidden
			/>
			<Square
				className={cn(
					'xy-send-stop-icon absolute h-3 w-3 fill-current',
					showStop ? 'scale-100 opacity-100' : 'scale-90 opacity-0',
				)}
				aria-hidden
			/>
		</button>
	);
}

function MultiAgentChip({onExit}: {onExit: () => void}) {
	return (
		<div
			className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full border border-accent/40 bg-accent/10 px-2 font-mono text-[11px] text-accent"
			title="提示主模型偏向用 Agent 拆分并行子任务；不强制。关闭后仍可主动调用 Agent"
		>
			<Network className="h-3.5 w-3.5 text-accent" strokeWidth={1.9} />
			<span>Multi-Agent</span>
			<button
				type="button"
				aria-label="退出 Multi-Agent"
				title="退出 Multi-Agent"
				className="flex h-5 w-5 items-center justify-center rounded-full text-mute hover:bg-paper-deep hover:text-ink"
				onClick={onExit}
			>
				<X className="h-3 w-3" strokeWidth={2} />
			</button>
		</div>
	);
}

export function Composer({showTodoDock = true}: {showTodoDock?: boolean}) {
	const [value, setValueState] = useState('');
	const [attachments, setAttachments] = useState<Attachment[]>([]);
	const [uploading, setUploading] = useState(false);
	const uploadCountRef = useRef(0);
	const sendAcceptPendingRef = useRef(false);
	const [dragOver, setDragOver] = useState(false);
	const fileRef = useRef<HTMLInputElement>(null);
	const taRef = useRef<HTMLTextAreaElement>(null);
	const attachmentsRef = useRef(attachments);
	attachmentsRef.current = attachments;
	const activeId = useChatUiStore(s => s.activeId);
	const activeSessionIsSide = useChatUiStore(
		s => s.sessions.find(session => session.id === activeId)?.spaceId === SIDE_SPACE_ID,
	);
	const activeSessionArchived = useChatUiStore(
		s => Boolean(activeId && s.sessions.find(session => session.id === activeId)?.archived),
	);
	const restoreSession = useChatUiStore(s => s.restoreSession);
	const activeInboxBackendId = useChatUiStore(s =>
		activeId ? activeBackendSessionId(s.historyById, activeId) : '',
	);
	const statusText = useChatUiStore(
		s => selectActiveSessionStream(s).statusText,
	);
	const sendMessage = useChatUiStore(s => s.sendMessage);
	const chatUiStoreApi = useChatUiStoreApi();
	const stopGeneration = useChatUiStore(s => s.stopGeneration);
	const composerInsertSeq = useChatUiStore(s => s.composerInsertSeq);
	const composerFocusSeq = useChatUiStore(s => s.composerFocusSeq);
	const composerDraftRestoreSeq = useChatUiStore(s => s.composerDraftRestoreSeq);
	const composerDraftRestoreSessionId = useChatUiStore(s => s.composerDraftRestoreSessionId);
	const composerDraftClearSeq = useChatUiStore(s => s.composerDraftClearSeq);
	const composerDraftClearRequest = useChatUiStore(s => s.composerDraftClearRequest);
	const model = useSettingsStore(s => s.model);
	const apiKey = useSettingsStore(s => s.apiKey);
	const provider = useSettingsStore(s => s.provider);
	const openSettings = useSettingsStore(s => s.openSettings);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const hasPendingDock = useHasComposerPendingDock();
	const todoDockLive = useSessionTodoDockLive();
	const hasTodoDock = showTodoDock && todoDockLive;
	const goalDockLive = useSessionGoalDockLive();
	const isComposerFused = hasPendingDock || hasTodoDock || goalDockLive;
	const agentMode = useChatUiStore(s => s.agentMode);
	const setAgentMode = useChatUiStore(s => s.setAgentMode);
	const remoteLoggedIn = useRemoteStore(s => s.loggedIn);
	const permissionMode = useSettingsStore(s => s.permissionMode);
	const updateSettings = useSettingsStore(s => s.update);
	const [previewImage, setPreviewImage] = useState<ImageAttachment | null>(null);
	const [modelOpen, setModelOpen] = useState(false);
	const [quickMenuOpen, setQuickMenuOpen] = useState(false);
	/** smoke-test #8：+ 菜单里的 MCP 面板（搜索 + Manage + 空态）。 */
	const [mcpOpen, setMcpOpen] = useState(false);
	const [multiAgent, setMultiAgent] = useState(false);
	/** 会话输入框手动选的思考等级；空 = 该模型默认/会话级。 */
	const [reasoningEffort, setReasoningEffort] = useState('');
	// 活动模型在设置里勾选的思考等级；未勾选 = 未限定（手选回落自动）。
	const activeModelLevels = useSettingsStore(s => {
		const p = s.profiles.find(pp => pp.id === s.activeProfileId);
		return p?.models?.find(mm => mm.id === s.model)?.reasoningLevels;
	});
	const levelOptions = useMemo(
		() => activeModelLevels ?? [],
		[activeModelLevels],
	);
	// 手选等级跌出当前模型支持集（切换模型/改设置）→ 回落「自动」。
	useEffect(() => {
		if (
			reasoningEffort &&
			!levelOptions.includes(reasoningEffort as ReasoningEffort)
		) {
			setReasoningEffort('');
		}
	}, [levelOptions, reasoningEffort]);
	// P1 mid-turn inbox：排队 chip（会话忙时后端 202 排队；轮询刷新/逐条取消）。
	const inboxBySession = useChatUiStore(s => s.inboxBySession);
	const refreshInbox = useChatUiStore(s => s.refreshInbox);
	const cancelInboxItem = useChatUiStore(s => s.cancelInboxItem);
	const editInboxItem = useChatUiStore(s => s.editInboxItem);
	const inboxItems: InboxQueuedItem[] = (activeId ? inboxBySession[activeId] : undefined) ?? [];
	// 每会话派生：切走再切回时不会因其它会话的轮询结果把本会话 chip 熄灭。
	const hasInboxChip = inboxItems.length > 0;
	const queueSessionBusy = useChatUiStore(s => {
		if (!activeId) return false;
		const stream = selectActiveSessionStream(s);
		return (
			sessionStreamActive(s, activeId) ||
			Boolean(stream.remoteStreaming || stream.turnDetached)
		);
	});
	const manualQueueResumeAvailable = canManuallyResumeInbox(
		activeSessionArchived,
		queueSessionBusy,
		inboxItems,
	);
	const inboxPollingActive = useChatUiStore(s => {
		if (!activeId || s.sessions.find(session => session.id === activeId)?.spaceId === SIDE_SPACE_ID) return false;
		const stream = selectActiveSessionStream(s);
		return (
			hasInboxChip ||
			sessionStreamActive(s, activeId) ||
			Boolean(stream.remoteStreaming || stream.turnDetached)
		);
	});
	// 队列列表：全部条目可见（默认最多 3 条，超出折叠）。
	const [queueExpanded, setQueueExpanded] = useState(false);
	const prioritizedInbox = prioritizeInboxPreview(inboxItems);
	const visibleInbox = queueExpanded
		? prioritizedInbox
		: prioritizedInbox.slice(0, QUEUE_PREVIEW_COUNT);
	const hiddenInboxCount = inboxItems.length - visibleInbox.length;
	// 行内编辑：editingId 锁定目标条目——轮询导致的队列位移不会再改错行。
	// Enter/失焦保存；Esc 取消（escRef 拦住失焦触发的保存，避免误保存）。
	const [editingId, setEditingId] = useState<string | null>(null);
	const [queueDraft, setQueueDraft] = useState('');
	const queueEscRef = useRef(false);
	const [queueActionsInFlight, setQueueActionsInFlight] = useState<Set<string>>(
		() => new Set(),
	);
	const queueActionsInFlightRef = useRef(new Set<string>());
	const runQueueAction = async (
		queueId: string,
		action: () => Promise<boolean>,
		failureText: string,
	): Promise<boolean> => {
		if (queueActionsInFlightRef.current.has(queueId)) return false;
		queueActionsInFlightRef.current.add(queueId);
		setQueueActionsInFlight(new Set(queueActionsInFlightRef.current));
		try {
			const ok = await action();
			if (!ok) toast.error(failureText);
			return ok;
		} catch (error) {
			toast.error(error instanceof Error ? error.message : failureText);
			return false;
		} finally {
			queueActionsInFlightRef.current.delete(queueId);
			setQueueActionsInFlight(new Set(queueActionsInFlightRef.current));
		}
	};
	const editingTargetRef = useRef<{
		sessionId: string;
		item: InboxQueuedItem;
	} | null>(null);
	const closeQueueEdit = () => {
		editingTargetRef.current = null;
		setEditingId(null);
		setQueueDraft('');
	};
	useEffect(() => {
		closeQueueEdit();
		setQueueExpanded(false);
	}, [activeId, activeInboxBackendId, activeSessionArchived]);
	const openQueueEdit = (it: InboxQueuedItem) => {
		if (!canEditInboxItem(it.state, activeSessionArchived) || !activeId) return;
		queueEscRef.current = false;
		editingTargetRef.current = {sessionId: activeId, item: it};
		setEditingId(it.queue_id);
		setQueueDraft(it.text);
	};
	const saveQueueEdit = () => {
		// Esc 取消路径：跳过这次由失焦触发的调用。
		if (queueEscRef.current) {
			queueEscRef.current = false;
			closeQueueEdit();
			return;
		}
		const target = editingTargetRef.current;
		const t = queueDraft.trim();
		closeQueueEdit();
		if (
			target &&
			chatUiStoreApi.getState().sessions.some(session =>
				session.id === target.sessionId && session.archived,
			)
		) {
			toast.info('归档对话为只读，请先恢复后编辑');
			return;
		}
		if (!target || !t || t === target.item.text) return;
		if (!canMutateInboxItem(target.item.state)) {
			// 编辑期间被投递：保存必 409，直接提示而不是静默丢改动。
			toast.error('该消息已开始投递，无法编辑');
			return;
		}
		void runQueueAction(
			target.item.queue_id,
			() => editInboxItem(target.sessionId, target.item.queue_id, t),
			'编辑失败（消息可能已开始投递）',
		).then(async saved => {
			if (saved) return;
			await refreshInbox(target.sessionId);
			if (
				chatUiStoreApi.getState().activeId !== target.sessionId ||
				editingTargetRef.current
			) {
				return;
			}
			const latest = chatUiStoreApi.getState();
			if (
				latest.sessions.some(
					session => session.id === target.sessionId && session.archived,
				)
			) {
				return;
			}
			const current = latest.inboxBySession[target.sessionId]?.find(
				item => item.queue_id === target.item.queue_id,
			);
			if (!current || !canEditInboxItem(current.state)) return;
			// 保存失败时保留用户输入；消息若已进入投递态则由刷新结果决定，
			// 不会把一个已不能编辑的旧队列项重新打开。
			editingTargetRef.current = {sessionId: target.sessionId, item: current};
			setEditingId(current.queue_id);
			setQueueDraft(t);
		});
	};
	const cancelQueueItem = (it: InboxQueuedItem) => {
		const sessionId = activeId;
		if (!sessionId) return;
		if (
			activeSessionArchived ||
			chatUiStoreApi.getState().sessions.some(
				session => session.id === sessionId && session.archived,
			)
		) {
			toast.info('归档对话为只读，请先恢复后取消排队消息');
			return;
		}
		if (it.queue_id === editingId) closeQueueEdit();
		void runQueueAction(
			it.queue_id,
			() => cancelInboxItem(sessionId, it.queue_id),
			'取消失败（消息可能已开始投递）',
		);
	};
	// 会话切换时先取快照；运行中快速轮询，空闲时低频同步其它客户端入队。
	useEffect(() => {
		if (!activeId || activeSessionIsSide) {
			return;
		}
		let disposed = false;
		let timer: number | undefined;
		const tick = async () => {
			const applied = await refreshInbox(activeId);
			if (disposed) return;
			// Schedule after completion so a slow server cannot accumulate overlapping
			// requests. Failed snapshots retry sooner and never clear the current cards.
			const delay = applied ? (inboxPollingActive ? 2000 : 10000) : 5000;
			timer = window.setTimeout(() => void tick(), delay);
		};
		void tick();
		return () => {
			disposed = true;
			if (timer !== undefined) window.clearTimeout(timer);
		};
	}, [inboxPollingActive, activeId, activeSessionIsSide, activeInboxBackendId, refreshInbox]);
	const [taCapped, setTaCapped] = useState(false);
	const [taExpanded, setTaExpanded] = useState(false);
	/** 光标位置：slash 弹层按「光标处词元」判定，支持消息中途输入 / 唤起。 */
	const [taCaret, setTaCaret] = useState(0);
	/** 拖选方向：自绘光标跟 focus 端,与原生 caret 行为一致。 */
	const [taCaretDir, setTaCaretDir] = useState<'forward' | 'backward' | 'none'>('forward');
	/** textarea 聚焦态:自绘光标聚焦浮现、失焦隐没。 */
	const [taFocused, setTaFocused] = useState(false);
	/** Esc / 点击外部临时关闭弹层；输入变化后自动恢复。 */
	const [slashDismissed, setSlashDismissed] = useState(false);
	/** 弹层键盘高亮（扁平列表下标：技能组在前、命令组在后）；hover 与键盘共用。 */
	const [slashHighlight, setSlashHighlight] = useState<number | null>(null);
	const [slashExecuting, setSlashExecuting] = useState(false);
	const [slashExecutingName, setSlashExecutingName] = useState('');
	const slashExecutingRef = useRef(false);
	/** IME 组词期间关闭着色覆盖层，避免合成文字被 text-transparent 隐藏。 */
	const [imeComposing, setImeComposing] = useState(false);
	/** 当前工作区技能清单（/ 弹层与着色候选；按 workspace 缓存）。 */
	const [slashSkills, setSlashSkills] = useState<SkillInfo[]>([]);
	const [slashSkillsWorkspace, setSlashSkillsWorkspace] = useState('');
	const taExpandedRef = useRef(false);
	/** 自动高度调度器(rAF 批处理 + 写保护,契约见 lib/taAutoResize.ts)。 */
	const taAutoResizeRef = useRef<ReturnType<typeof createTaAutoResize> | null>(null);
	if (!taAutoResizeRef.current) {
		taAutoResizeRef.current = createTaAutoResize({
			minPx: TA_MIN_PX,
			maxPx: TA_MAX_PX,
			isExpanded: () => taExpandedRef.current,
			onCapped: setTaCapped,
		});
	}
	const modelMenuRef = useRef<HTMLDivElement>(null);
	const quickMenuRef = useRef<HTMLDivElement>(null);
	const modelMenuId = useId();
	const quickMenuId = useId();
	/** 点选候选项后待应用的光标位置（等 DOM value 提交后再 setSelectionRange）。 */
	const pendingCaretRef = useRef<number | null>(null);
	/** 自绘光标重测出口(TypingCaret):textarea 滚动后视觉坐标重算。 */
	const caretApiRef = useRef<TypingCaretApi | null>(null);
	const activeIdRef = useRef(activeId);
	const draftRevisionRef = useRef(new Map<string, number>());
	const draftRevisionFor = (sessionId: string | null | undefined) =>
		draftRevisionRef.current.get(sessionId ?? '\0empty-composer') ?? 0;
	const setValue = (
		next: string,
		sessionId: string | null = activeIdRef.current ?? activeId,
	) => {
		const key = sessionId ?? '\0empty-composer';
		draftRevisionRef.current.set(key, draftRevisionFor(sessionId) + 1);
		setValueState(next);
	};
	const composerMountedRef = useRef(false);
	const valueRef = useRef(value);
	valueRef.current = value;
	useEffect(() => {
		composerMountedRef.current = true;
		return () => {
			composerMountedRef.current = false;
		};
	}, []);
	const beginUpload = () => {
		uploadCountRef.current += 1;
		setUploading(true);
	};
	const endUpload = () => {
		uploadCountRef.current = Math.max(0, uploadCountRef.current - 1);
		if (composerMountedRef.current) {
			setUploading(uploadCountRef.current > 0);
		}
	};
	const currentSessionStreaming = useChatUiStore(s =>
		activeId ? sessionStreamActive(s, activeId) : false,
	);
	const images = attachments.filter(
		(a): a is ImageAttachment => a.kind === 'image',
	);
	const files = attachments.filter(
		(a): a is FileAttachment => a.kind === 'file',
	);

	const multiAgentRef = useRef(multiAgent);
	multiAgentRef.current = multiAgent;
	const agentModeRef = useRef(agentMode);
	agentModeRef.current = agentMode;
	const permissionModeRef = useRef(permissionMode);
	permissionModeRef.current = permissionMode;
	const reasoningEffortRef = useRef(reasoningEffort);
	reasoningEffortRef.current = reasoningEffort;

	/** 按 session 保存/恢复：输入草稿 + Agent/审批/多 Agent 模式。 */
	useLayoutEffect(() => {
		const prevId = activeIdRef.current;
		if (prevId && prevId !== activeId) {
			setComposerDraft(prevId, {
				text: valueRef.current,
				attachments: attachmentsRef.current,
				agentMode: normalizeAgentMode(agentModeRef.current),
				permissionMode: permissionModeRef.current,
				multiAgent: multiAgentRef.current,
				reasoningEffort: reasoningEffortRef.current,
			});
		}
		const loaded = activeId
			? (getComposerDraft(activeId) ??
				defaultComposerDraft({
					permissionMode: useSettingsStore.getState().permissionMode,
				}))
			: defaultComposerDraft({
					permissionMode: useSettingsStore.getState().permissionMode,
				});
		setValueState(loaded.text);
		const restoredCaret = loaded.text.length;
		setTaCaret(restoredCaret);
		setTaCaretDir('forward');
		requestAnimationFrame(() => {
			if (activeIdRef.current !== activeId || valueRef.current !== loaded.text) {
				return;
			}
			taRef.current?.setSelectionRange(restoredCaret, restoredCaret);
		});
		setAttachments(loaded.attachments.slice());
		setMultiAgent(loaded.multiAgent);
		setAgentMode(loaded.agentMode);
		setReasoningEffort(loaded.reasoningEffort);
		if (useSettingsStore.getState().permissionMode !== loaded.permissionMode) {
			updateSettings({permissionMode: loaded.permissionMode});
		}
		activeIdRef.current = activeId;
	}, [activeId, setAgentMode, updateSettings]);

	/** 卸载时落盘当前会话草稿，避免快速切走丢字。 */
	useEffect(() => {
		return () => {
			const id = activeIdRef.current;
			if (!id) {
				return;
			}
			setComposerDraft(id, {
				text: valueRef.current,
				attachments: attachmentsRef.current,
				agentMode: normalizeAgentMode(agentModeRef.current),
				permissionMode: permissionModeRef.current,
				multiAgent: multiAgentRef.current,
				reasoningEffort: reasoningEffortRef.current,
			});
		};
	}, []);

	/** 模式变更写入当前会话草稿，保证切回时能还原。 */
	useEffect(() => {
		const id = activeIdRef.current;
		if (!id) {
			return;
		}
		patchComposerDraftModes(id, {
			agentMode: normalizeAgentMode(agentMode),
			permissionMode,
			multiAgent,
		});
	}, [agentMode, permissionMode, multiAgent]);

	/** 思考等级变更写入草稿：切走再切回、或重开会话时不丢手选等级。 */
	useEffect(() => {
		const id = activeIdRef.current;
		if (!id) {
			return;
		}
		patchComposerDraftModes(id, {reasoningEffort});
	}, [reasoningEffort]);

	useEffect(() => {
		if (composerInsertSeq === 0) {
			return;
		}
		const snip = chatUiStoreApi.getState().lastComposerInsert;
		if (!snip) {
			return;
		}
		const path = snip.path?.trim() || undefined;
		const text = snip.text;
		if (!path && !text) {
			return;
		}
		setAttachments(prev => {
			if (path) {
				if (
					prev.some(
						a => a.kind === 'file' && a.path === path,
					)
				) {
					return prev;
				}
				return [
					...prev,
					{
						kind: 'file',
						id: uid('file'),
						name: snip.name,
						path,
					},
				];
			}
			if (
				prev.some(
					a =>
						a.kind === 'file' &&
						!a.path &&
						a.name === snip.name &&
						a.text === text,
				)
			) {
				return prev;
			}
			return [
				...prev,
				{
					kind: 'file',
					id: uid('snip'),
					name: snip.name,
					text,
				},
			];
		});
	}, [chatUiStoreApi, composerInsertSeq]);

	useEffect(() => {
		if (composerFocusSeq === 0) {
			return;
		}
		taRef.current?.focus();
	}, [composerFocusSeq]);

	useEffect(() => {
		if (
			composerDraftRestoreSeq === 0 ||
			!composerDraftRestoreSessionId ||
			activeIdRef.current !== composerDraftRestoreSessionId
		) {
			return;
		}
		const draft = getComposerDraft(composerDraftRestoreSessionId);
		if (!draft) return;
		for (const attachment of attachmentsRef.current) {
			if (attachment.kind === 'image' && attachment.previewUrl.startsWith('blob:')) {
				URL.revokeObjectURL(attachment.previewUrl);
			}
		}
		const restoredText = draft.text;
		setValue(restoredText, composerDraftRestoreSessionId);
		setTaCaret(restoredText.length);
		setTaCaretDir('forward');
		setAttachments(draft.attachments.slice());
		const frame = requestAnimationFrame(() => {
			if (
				activeIdRef.current !== composerDraftRestoreSessionId ||
				valueRef.current !== restoredText
			) {
				return;
			}
			taRef.current?.focus();
			taRef.current?.setSelectionRange(restoredText.length, restoredText.length);
		});
		return () => cancelAnimationFrame(frame);
	}, [composerDraftRestoreSeq, composerDraftRestoreSessionId]);

	useEffect(() => {
		const request = composerDraftClearRequest;
		if (
			composerDraftClearSeq === 0 ||
			!request ||
			activeIdRef.current !== request.sessionId
		) {
			return;
		}
		const currentAttachments = attachmentsRef.current;
		const currentMediaRefs = currentAttachments.flatMap(attachment =>
			attachment.kind === 'image' && attachment.mediaRef
				? [attachment.mediaRef]
				: [],
		);
		if (
			valueRef.current !== request.text ||
			currentAttachments.length !== request.mediaRefs.length ||
			currentMediaRefs.length !== request.mediaRefs.length ||
			currentMediaRefs.some((mediaRef, index) => mediaRef !== request.mediaRefs[index])
		) {
			return;
		}
		for (const attachment of currentAttachments) {
			if (attachment.kind === 'image' && attachment.previewUrl.startsWith('blob:')) {
				URL.revokeObjectURL(attachment.previewUrl);
			}
		}
		setComposerDraft(request.sessionId, {text: '', attachments: []});
		setValue('', request.sessionId);
		setTaCaret(0);
		setAttachments([]);
		requestAnimationFrame(() => applyTaHeight(false));
	}, [composerDraftClearSeq, composerDraftClearRequest]);

	useEffect(() => {
		if (!currentSessionStreaming) {
			return;
		}
		pushEscLayer('composer-stop', () => {
			const st = chatUiStoreApi.getState?.();
			if (st?.activeId && sessionStreamActive(st, st.activeId)) {
				void stopGeneration();
			}
		});
		return () => {
			popEscLayer('composer-stop');
		};
	}, [stopGeneration, currentSessionStreaming]);

	useEffect(() => {
		if (!modelOpen) {
			return;
		}
		const onDoc = (e: MouseEvent) => {
			if (!modelMenuRef.current?.contains(e.target as Node)) {
				setModelOpen(false);
			}
		};
		pushEscLayer('composer-model', () => setModelOpen(false));
		document.addEventListener('mousedown', onDoc);
		return () => {
			document.removeEventListener('mousedown', onDoc);
			popEscLayer('composer-model');
		};
	}, [modelOpen]);

	useEffect(() => {
		if (!quickMenuOpen) {
			return;
		}
		const onDoc = (e: MouseEvent) => {
			if (!quickMenuRef.current?.contains(e.target as Node)) {
				setQuickMenuOpen(false);
			}
		};
		pushEscLayer('composer-quick', () => setQuickMenuOpen(false));
		document.addEventListener('mousedown', onDoc);
		return () => {
			document.removeEventListener('mousedown', onDoc);
			popEscLayer('composer-quick');
		};
	}, [quickMenuOpen]);

	useEffect(() => {
		if (!taExpanded) {
			return;
		}
		pushEscLayer('composer-expand', () => applyTaHeightRef.current(false));
		return () => {
			popEscLayer('composer-expand');
		};
	}, [taExpanded]);

	useEffect(() => {
		if (remoteLoggedIn || uploading || currentSessionStreaming) {
			setQuickMenuOpen(false);
		}
	}, [currentSessionStreaming, remoteLoggedIn, uploading]);

	// 统一斜杠命令：候选只对输入开头的 slash 词元开放，与提交时的命令解析口径一致。
	// 前置空白允许；普通句子中间的 /xxx 按正文处理。@ 文件引用仍可出现在任意位置。
	const activeWorkspace = useChatStore(s => {
		const activeSession = s.sessions.find(session => session.id === s.activeId);
		if (activeSession?.spaceId === SIDE_SPACE_ID) {
			return '';
		}
		const spaceId = activeSession?.spaceId ?? s.activeSpaceId;
		return s.spaces.find(space => space.id === spaceId)?.rootPath ?? '';
	});
	const slashToken = useMemo(() => {
		const token = slashTokenAt(value, taCaret);
		return token && value.slice(0, token.start).trim() === '' ? token : null;
	}, [value, taCaret]);
	const slashIntent = slashToken !== null;
	const slashQuery = slashToken ? slashToken.text.slice(1).toLowerCase() : '';
	const slashSuggest = useMemo(
		() => (slashToken ? slashSuggestions(slashToken.text) : []),
		[slashToken],
	);

	// @ 文件引用：与 / 同一条词元检测核（triggerTokenAt），候选来自
	// GET /v1/references/files；选中插入 `@相对路径 `，由 Agent 按需读文件。
	const atToken = useMemo(() => triggerTokenAt(value, taCaret, '@'), [value, taCaret]);
	const atQuery = atToken ? atToken.text.slice(1) : '';
	const atWorkspace = activeWorkspace.trim();
	const atRequestKey = atToken ? fileReferenceQueryKey(atWorkspace, atQuery) : null;
	const [atResult, setAtResult] = useState<FileReferenceQueryResult | null>(null);
	const currentAtResult = currentFileReferenceResult(atResult, atRequestKey);
	const atFiles = currentAtResult?.files ?? [];
	const atLoaded = currentAtResult !== null;
	useEffect(() => {
		if (!atRequestKey || !taFocused) {
			setAtResult(null);
			return;
		}
		const requestKey = atRequestKey;
		const controller = new AbortController();
		const t = setTimeout(() => {
			void fetchFileReferences(atWorkspace, atQuery, controller.signal).then(report => {
				if (controller.signal.aborted || !report) {
					return;
				}
				setAtResult({key: requestKey, files: report.files});
			});
		}, 120);
		return () => {
			controller.abort();
			clearTimeout(t);
		};
	}, [atRequestKey, atQuery, atWorkspace, taFocused]);
	const atMenuOpen =
		atToken !== null &&
		taFocused &&
		!slashDismissed &&
		atLoaded &&
		atFiles.length > 0;

	// 光标处于 slash 词元、或输入以 / 开头（着色需要）时，拉取当前工作区的技能清单。
	const slashZone = slashIntent || value.startsWith('/');
	useEffect(() => {
		if (!slashZone) {
			return;
		}
		if (!activeWorkspace.trim()) {
			// Empty workspace means no workspace scope. Omitting the query would make
			// /v1/skills fall back to the server's global UI cwd (often another project).
			setSlashSkillsWorkspace('');
			setSlashSkills([]);
			return;
		}
		const cached = cachedSlashSkills(activeWorkspace);
		if (cached) {
			setSlashSkillsWorkspace(activeWorkspace);
			setSlashSkills(cached.skills);
			return;
		}
		setSlashSkillsWorkspace(activeWorkspace);
		setSlashSkills([]);
		let cancelled = false;
		void loadSlashSkills(activeWorkspace).then(report => {
			if (cancelled || report.ok === false) {
				return; // 失败不缓存：下次唤起弹层重试。
			}
			setSlashSkills(report.skills);
		});
		return () => {
			cancelled = true;
		};
	}, [slashZone, activeWorkspace]);
	const activeSlashSkills =
		slashSkillsWorkspace === activeWorkspace
			? slashSkills
			: EMPTY_SLASH_SKILLS;

	// 技能候选按词元关键词过滤（名称包含即可），空词元展示全部。
	const filteredSkills = useMemo(() => {
		if (!slashQuery) {
			return activeSlashSkills;
		}
		return activeSlashSkills.filter(s => s.name.toLowerCase().includes(slashQuery));
	}, [activeSlashSkills, slashQuery]);

	// 弹层只在光标位于 slash 词元时出现；此前 slashSkills 残留导致删除 / 后关不掉。
	const slashMenuOpen =
		slashIntent &&
		taFocused &&
		!slashDismissed &&
		(slashSuggest.length > 0 || filteredSkills.length > 0);

	// 扁平候选项（渲染序：技能组在前、命令组在后）——键盘仲裁与行高亮共用。
	const slashFlatItems = useMemo(
		() => [
			...filteredSkills.map(s => ({kind: 'skill' as const, replacement: `/${s.name} `})),
			...slashSuggest.map(c => ({kind: 'command' as const, replacement: `/${c.name} `})),
		],
		[filteredSkills, slashSuggest],
	);
	// @ 候选扁平列表（与 slash 弹层互斥：词元首字符不同，二者不会同时开）。
	const atFlatItems = useMemo(
		() => atFiles.map(f => ({kind: 'file' as const, replacement: `@${f} `})),
		[atFiles],
	);
	const popupItems = slashToken ? slashFlatItems : atFlatItems;
	const popupOpen = slashMenuOpen || atMenuOpen;

	// 词元/弹层变化即清高亮，防陈旧下标落在另一组行上。
	useEffect(() => {
		setSlashHighlight(null);
	}, [slashToken, atToken, popupOpen]);

	// 高亮行自动滚入可视区（命令面板 combobox 语义）：键盘 ↑↓ 走出视口时列表跟随，
	// block:'nearest' 保证视口内已有行不跳动。滚动条隐藏后这是唯一的导航可见反馈。
	const flyoutRef = useRef<HTMLDivElement>(null);
	useEffect(() => {
		const el = flyoutRef.current?.querySelector('[aria-selected="true"]');
		if (el && typeof el.scrollIntoView === 'function') {
			el.scrollIntoView({block: 'nearest'});
		}
	}, [slashHighlight, popupItems]);

	// 输入变化即解除临时关闭；Esc 关闭后继续输入 / 会重新出现。
	useEffect(() => {
		setSlashDismissed(false);
	}, [value]);

	// Esc 关闭弹层（走 escStack 顶层，优先于「停止生成」等更早入栈的层）。
	useEffect(() => {
		if (!popupOpen) {
			return;
		}
		pushEscLayer('composer-slash', () => setSlashDismissed(true));
		return () => popEscLayer('composer-slash');
	}, [popupOpen]);

	// 点选候选项后把光标放回替换点。
	useEffect(() => {
		if (pendingCaretRef.current == null) {
			return;
		}
		const pos = pendingCaretRef.current;
		pendingCaretRef.current = null;
		const el = taRef.current;
		if (el) {
			el.focus();
			el.setSelectionRange(pos, pos);
		}
	}, [value]);

	/** 用选中项替换光标处的 slash 词元（命令 usage 或 /<skill_name>）。 */
	const applySlashPick = (replacement: string) => {
		const tk = slashToken;
		if (!tk) {
			return;
		}
		const caret = tk.start + replacement.length;
		setValue(value.slice(0, tk.start) + replacement + value.slice(tk.end));
		setTaCaret(caret);
		pendingCaretRef.current = caret;
	};

	/** 用选中项替换光标处的 @ 词元（@相对路径）。 */
	const applyAtPick = (replacement: string) => {
		const tk = atToken;
		if (!tk) {
			return;
		}
		const caret = tk.start + replacement.length;
		setValue(value.slice(0, tk.start) + replacement + value.slice(tk.end));
		setTaCaret(caret);
		pendingCaretRef.current = caret;
	};

	// slash 着色 + ghost hint:由「镜像覆盖层 + 自绘光标」(TypingCaret)统一渲染。
	// 仅输入首词元按命令/技能着色，和执行门禁一致；这里只算字符区间(闭开,UTF-16)。
	// URL(https://…)、路径(src/foo)整体是一个非空白词元,不会误着色。
	const caretColoring = useMemo(() => {
		if (imeComposing || !value.includes('/')) {
			return {ranges: [] as CaretColorRange[], hint: ''};
		}
		const ranges: CaretColorRange[] = [];
		const parts = value.split(/(\s+)/);
		const leadingStart = value.search(/\S/);
		let off = 0;
		let colored = false;
		for (const part of parts) {
			if (
				off === leadingStart &&
				part.startsWith('/') &&
				part.length > 1
			) {
				const color = slashLeadingColor(part.slice(1), activeSlashSkills);
				if (color) {
					colored = true;
					ranges.push({start: off, end: off + part.length});
				}
			}
			off += part.length;
		}
		// ghost hint(claim hint 语义):首词元精确命中命令/技能且参数空白时,
		// 在词元后展示灰字提示(零 DOM 侵入草稿,仅覆盖层显示,不参与提交)。
		const hint = slashGhostHint(value, activeSlashSkills) ?? '';
		return colored || hint ? {ranges, hint} : {ranges: [] as CaretColorRange[], hint: ''};
	}, [value, activeSlashSkills, imeComposing]);

	// 自绘光标接管条件:非 IME 且文本量在阈值内(超大文本退回原生,保编辑流畅)。
	// 接管时 textarea 文字隐藏(text-transparent),原生光标 caret-color: transparent。
	const CARET_MAX_CHARS = 2000;
	const caretOverlayActive = !imeComposing && value.length <= CARET_MAX_CHARS;

	useEffect(() => {
		if (!remoteLoggedIn) {
			return;
		}
		setAttachments(prev => {
			const next = [];
			for (const a of prev) {
				if (a.kind === 'image') {
					URL.revokeObjectURL(a.previewUrl);
					continue;
				}
				next.push(a);
			}
			return next;
		});
	}, [remoteLoggedIn]);

	useEffect(() => {
		return () => {
			for (const a of attachmentsRef.current) {
				if (a.kind === 'image') {
					URL.revokeObjectURL(a.previewUrl);
				}
			}
		};
	}, []);

	const resizeTa = () => {
		// 2026-09-08 打字跟手优化:测高+写入走 rAF 批处理(关键路径零回流),
		// 高度未变不写 style。契约见 lib/taAutoResize.ts。
		const el = taRef.current;
		if (!el) {
			return;
		}
		taAutoResizeRef.current?.schedule(el);
	};

	const applyTaHeight = (expanded: boolean) => {
		setTaExpanded(expanded);
		taExpandedRef.current = expanded;
		const el = taRef.current;
		if (!el) {
			return;
		}
		if (expanded) {
			el.style.overflowY = 'auto';
			el.style.height = TA_EXPANDED_HEIGHT;
			return;
		}
		resizeTa();
	};

	const applyTaHeightRef = useRef(applyTaHeight);
	applyTaHeightRef.current = applyTaHeight;

	useEffect(() => {
		resizeTa();
	}, [value]);
	// 卸载时取消未落盘的 rAF 测高回调
	useEffect(() => () => taAutoResizeRef.current?.cancel(), []);

	const removeAttachment = (id: string) => {
		setAttachments(prev => {
			const target = prev.find(a => a.id === id);
			if (target?.kind === 'image') {
				URL.revokeObjectURL(target.previewUrl);
			}
			return prev.filter(a => a.id !== id);
		});
	};

	const addImages = (list: File[]) => {
		const next: ImageAttachment[] = [];
		for (const file of list) {
			if (!file.type.startsWith('image/')) {
				continue;
			}
			if (file.size > MAX_IMAGE_BYTES) {
				toast.warn(`图片 ${file.name} 超过 8MB`);
				continue;
			}
			next.push({
				kind: 'image',
				id: uid('img'),
				name: file.name || 'paste.png',
				previewUrl: URL.createObjectURL(file),
				mime: file.type || 'image/png',
				bytes: file.size,
				file,
			});
		}
		if (next.length === 0) {
			return;
		}
		setAttachments(prev => {
			const room = MAX_IMAGES - prev.filter(a => a.kind === 'image').length;
			if (room <= 0) {
				for (const n of next) {
					URL.revokeObjectURL(n.previewUrl);
				}
				toast.warn(`最多添加 ${MAX_IMAGES} 张图片`);
				return prev;
			}
			const take = next.slice(0, room);
			for (const n of next.slice(room)) {
				URL.revokeObjectURL(n.previewUrl);
			}
			return [...prev, ...take];
		});
	};

	const onPickFiles = async (fileList: FileList | File[] | null) => {
		if (!fileList) {
			return;
		}
		const originSessionId = activeId;
		const originText = valueRef.current;
		const originAttachments = attachmentsRef.current;
		let uploadStarted = false;
		const appendUploadedFile = (attachment: FileAttachment) => {
			const sameSessionIsActive =
				composerMountedRef.current &&
				activeIdRef.current === originSessionId &&
				chatUiStoreApi.getState().activeId === originSessionId;
			if (sameSessionIsActive) {
				setAttachments(current => [...current, attachment]);
				return;
			}
			if (!originSessionId) {
				toast.info('附件已上传，但原草稿没有关联会话，未加入当前对话');
				return;
			}
			const draft = getComposerDraft(originSessionId) ??
				defaultComposerDraft({text: originText, attachments: originAttachments});
			setComposerDraft(originSessionId, {
				text: draft.text,
				attachments: [...draft.attachments, attachment],
			});
		};
		try {
			const arr = Array.from(fileList);
			const imgs = arr.filter(f => f.type.startsWith('image/'));
			const others = arr.filter(f => !f.type.startsWith('image/'));
			if (others.length > 0) {
				beginUpload();
				uploadStarted = true;
			}
			if (imgs.length && !remoteLoggedIn) {
				addImages(imgs);
			}
			for (const file of others) {
				try {
					const res = await uploadFile(file);
					const body = res.text ?? '';
					const MAX_UPLOAD_SNIPPET = 48_000;
					if (body.length > MAX_UPLOAD_SNIPPET) {
						toast.warn(
							`${res.filename || file.name} 较大，已按文件名引用（不内联全文）`,
						);
						appendUploadedFile({
							kind: 'file',
							id: uid('file'),
							name: res.filename || file.name,
							path: res.filename || file.name,
						});
					} else {
						appendUploadedFile({
							kind: 'file',
							id: uid('file'),
							name: res.filename || file.name,
							text: body,
						});
					}
				} catch (err) {
					toast.error(err instanceof Error ? err.message : String(err));
					return;
				}
			}
		} finally {
			if (uploadStarted) endUpload();
			// Reset on every exit path, including a failed upload, so selecting the
			// same file again reliably fires the input's change event.
			if (fileRef.current) fileRef.current.value = '';
		}
	};

	const onPaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
		const items = e.clipboardData?.items;
		if (!items) {
			return;
		}
		const imageFiles: File[] = [];
		for (const item of items) {
			if (item.kind === 'file' && item.type.startsWith('image/')) {
				const f = item.getAsFile();
				if (f) {
					imageFiles.push(f);
				}
			}
		}
		if (imageFiles.length === 0 || remoteLoggedIn) {
			return;
		}
		e.preventDefault();
		addImages(imageFiles);
	};

	const buildPayload = (
		baseText = value,
		payloadAttachments: Attachment[] = attachments,
	) => {
		const parts = [baseText.trim()];
		for (const a of payloadAttachments) {
			if (a.kind !== 'file') continue;
			if (a.path && !a.text) {
				// @相对路径引用：由 Agent 按需读文件
				const ref = a.path.replace(/\\/g, '/');
				parts.push(`\n\n@${ref}`);
			} else if (a.text) {
				parts.push(`\n\n[附件: ${a.name}]\n\`\`\`\n${a.text}\n\`\`\`\n`);
			} else if (a.path) {
				parts.push(`\n\n@${a.path.replace(/\\/g, '/')}`);
			}
		}
		const payloadImages = payloadAttachments.filter(
			(a): a is ImageAttachment => a.kind === 'image',
		);
		return {
			text: parts.join('').trim() || (payloadImages.length > 0 ? '请分析这些图片。' : ''),
			mediaRefs: payloadImages.flatMap(image => (image.mediaRef ? [image.mediaRef] : [])),
		};
	};

	const ensureMediaRefs = async (
		imagesToUpload: ImageAttachment[] = images,
		targetSessionId: string | null = activeId,
		targetText = value,
	): Promise<string[]> => {
		const refs: string[] = [];
		const needsUpload = imagesToUpload.some(image => !image.mediaRef);
		if (needsUpload) beginUpload();
		try {
			for (const image of imagesToUpload) {
				if (image.mediaRef) {
					refs.push(image.mediaRef);
					continue;
				}
				if (!image.file) {
					throw new Error(`图片 ${image.name} 尚未准备好，请重新添加`);
				}
				const uploaded = await uploadMedia(image.file);
				refs.push(uploaded.media_ref);
				if (
					chatUiStoreApi.getState().activeId === targetSessionId &&
					activeIdRef.current === targetSessionId
				) {
					setAttachments(prev =>
						prev.map(item =>
							item.id === image.id && item.kind === 'image'
								? {...item, mediaRef: uploaded.media_ref}
								: item,
						),
					);
				} else if (targetSessionId) {
					const draft = getComposerDraft(targetSessionId);
					setComposerDraft(targetSessionId, {
						text: draft?.text ?? targetText,
						attachments: (draft?.attachments ?? imagesToUpload).map(item =>
							item.id === image.id && item.kind === 'image'
								? {...item, mediaRef: uploaded.media_ref}
								: item,
						),
					});
				}
			}
			return refs;
		} finally {
			if (needsUpload) endUpload();
		}
	};

	const canSend =
		!remoteLoggedIn &&
		!activeSessionArchived &&
		!uploading &&
		!slashExecuting &&
		(Boolean(value.trim()) || attachments.length > 0);

	const onSend = (mode: SendMode = 'send') => {
		if (activeSessionArchived) {
			toast.info('该对话已归档，请先恢复后发送');
			return;
		}
		if (remoteLoggedIn) return;
		if (sendAcceptPendingRef.current) return;
		if (uploadCountRef.current > 0) {
			toast.info('附件仍在上传，请完成后发送');
			return;
		}
		if (slashExecutingRef.current) return;
		// 斜杠命令网关：/xxx 先在本机（本地命令/技能直呼/未知命令提示）或
		// POST /v1/slash（server 命令）执行。命中则拦截，不当作普通消息发给模型
		// （修复 /export、/map、/run、/mode 等在 GUI 主输入框被当作普通文本发送）。
		// 非斜杠输入由 parseSlashInput 判 not-slash → consumed=false，走正常发送。
		const valueTrim = value.trim();
		if (valueTrim.startsWith('/')) {
			const sessId = activeId ?? '';
			const st = useChatStore.getState();
			const sessionBusyAtSubmit =
				sessId !== '' && sessionStreamActive(chatUiStoreApi.getState(), sessId);
			const submittedDraft = value;
			const submittedDraftRevision = draftRevisionFor(sessId || null);
			const submittedAttachments = attachmentsRef.current;
			const submittedAgentMode = agentModeRef.current;
			const submittedMultiAgent = multiAgentRef.current;
			const submittedReasoningEffort = reasoningEffortRef.current;
			let slashSentMessage = false;
			slashExecutingRef.current = true;
			setSlashExecuting(true);
			setSlashExecutingName(valueTrim.split(/\s+/, 1)[0] || '/命令');
			void (async () => {
				try {
					const consumed = await handleComposerSlash(valueTrim, {
						sessionId: sessId,
						backendSessionId:
							activeBackendSessionId(st.historyById, sessId) || undefined,
						workspace: activeWorkspace,
						sessionBusy: sessionBusyAtSubmit,
						onNewSession: () =>
							newSession(
								st.sessions.find(session => session.id === sessId)?.spaceId === SIDE_SPACE_ID
									? {side: true}
									: {spaceId: st.sessions.find(session => session.id === sessId)?.spaceId},
							),
						onRetryLast: async () => {
							const last = lastUserMessage(sessId);
							if (last) {
								const accepted = await st.sendMessage(
									last.text,
									last.mediaRefs,
									[],
									submittedAgentMode,
									undefined,
									submittedMultiAgent,
									{
										sessionId: sessId,
										background: activeIdRef.current !== sessId,
										reasoningEffort: submittedReasoningEffort,
									},
								);
								if (!accepted) {
									toast.error('重试未被接受，/retry 已保留在输入框');
								}
								return accepted;
							} else {
								toast.info('还没有可重试的消息');
								return true;
							}
						},
						onSend: async commandText => {
							let mediaRefs: string[];
							try {
								mediaRefs = await ensureMediaRefs(
									submittedAttachments.filter(
										(attachment): attachment is ImageAttachment => attachment.kind === 'image',
									),
									sessId,
									submittedDraft,
								);
							} catch (err) {
								toast.error(err instanceof Error ? err.message : String(err));
								return false;
							}
							const payload = buildPayload(commandText, submittedAttachments);
							return await new Promise<boolean>(resolve => {
								let settled = false;
								const settle = (accepted: boolean) => {
									if (settled) return;
									settled = true;
									resolve(accepted);
								};
								void st
									.sendMessage(
										payload.text,
										mediaRefs,
										[],
										submittedAgentMode,
										() => {
										slashSentMessage = true;
										settle(true);
										},
										submittedMultiAgent,
										{
											sessionId: sessId,
											background: activeIdRef.current !== sessId,
											reasoningEffort: submittedReasoningEffort,
											steerIfBusy: mode === 'steer',
										},
									)
									.then(settle)
									.catch(err => {
										if (!settled) {
											toast.error(err instanceof Error ? err.message : String(err));
										}
										settle(false);
									});
							});
						},
					});
					if (consumed && sessId) {
						const originDraft = getComposerDraft(sessId);
						const originActive =
							chatUiStoreApi.getState().activeId === sessId &&
							activeIdRef.current === sessId;
						const currentOriginText = originActive
							? valueRef.current
							: originDraft?.text;
						const currentOriginAttachments = originActive
							? attachmentsRef.current
							: originDraft?.attachments ?? [];
						if (currentOriginText !== undefined) {
							const {removed, remaining} = slashSentMessage
								? removeSubmittedAttachments(currentOriginAttachments, submittedAttachments)
								: {removed: [], remaining: currentOriginAttachments};
							const textUnchanged =
								currentOriginText === submittedDraft &&
								draftRevisionFor(sessId || null) === submittedDraftRevision;
							setComposerDraft(sessId, {
								text: textUnchanged ? '' : currentOriginText,
								// 普通命令保留附件；技能/改写命令已发送同一组附件时清掉。
								attachments: remaining,
							});
							if (originActive) {
								if (textUnchanged) {
								setValue('');
								}
								if (removed.length > 0) {
									for (const attachment of removed) {
										if (attachment.kind === 'image' && attachment.previewUrl.startsWith('blob:')) {
											URL.revokeObjectURL(attachment.previewUrl);
										}
									}
									setAttachments(remaining);
								}
								if (textUnchanged || removed.length > 0) {
								requestAnimationFrame(() => {
									applyTaHeight(false);
									taRef.current?.focus();
								});
								}
							} else if (removed.length > 0) {
								for (const attachment of removed) {
									if (attachment.kind === 'image' && attachment.previewUrl.startsWith('blob:')) {
										URL.revokeObjectURL(attachment.previewUrl);
									}
								}
							}
						}
					} else if (
						consumed &&
						!sessId &&
						chatUiStoreApi.getState().activeId == null &&
						valueRef.current === submittedDraft
					) {
						setValue('');
						requestAnimationFrame(() => {
							applyTaHeight(false);
							taRef.current?.focus();
						});
					}
				} catch (err) {
					toast.error(err instanceof Error ? err.message : String(err));
				} finally {
					slashExecutingRef.current = false;
					setSlashExecuting(false);
					setSlashExecutingName('');
				}
			})();
			return;
		}
		const payload = buildPayload();
		// 忙碌时允许发送：后端（P1 inbox）会 202 排队，settle 后自动投递——
		// 而不是静默丢弃或早退。仅远端模式 / 空文本 / 上传中仍拦。
		if (remoteLoggedIn || !payload.text || uploading) {
			return;
		}
		const sessionId = activeId;
		const draftText = value;
		const submittedDraftRevision = draftRevisionFor(sessionId);
		const draftAttachments = attachments;
		sendAcceptPendingRef.current = true;
		// 仅在服务端明确受理后清除；HTTP 拒绝时保留原草稿。
		void (async () => {
			let mediaRefs: string[];
			try {
				mediaRefs = await ensureMediaRefs(images, sessionId, draftText);
			} catch (err) {
				sendAcceptPendingRef.current = false;
				toast.error(err instanceof Error ? err.message : String(err));
				return;
			}
		const clearAfterAccept = () => {
			if (clearedByCallback) {
				return;
			}
			clearedByCallback = true;
			sendAcceptPendingRef.current = false;
				const acceptedSessionId = sessionId ?? chatUiStoreApi.getState().activeId;
			if (!acceptedSessionId) {
				return;
			}
			const originActive =
				chatUiStoreApi.getState().activeId === acceptedSessionId &&
				activeIdRef.current === acceptedSessionId;
			const acceptedDraft = getComposerDraft(acceptedSessionId);
			const currentText = originActive ? valueRef.current : acceptedDraft?.text;
			if (currentText === undefined) return;
			const currentAttachments = originActive
				? attachmentsRef.current
				: acceptedDraft?.attachments ?? [];
			const {removed, remaining} = removeSubmittedAttachments(
				currentAttachments,
				draftAttachments,
			);
			const textUnchanged =
				currentText === draftText &&
				draftRevisionFor(sessionId ?? acceptedSessionId) ===
					submittedDraftRevision;
			setComposerDraft(acceptedSessionId, {
				text: textUnchanged ? '' : currentText,
				attachments: remaining,
				agentMode: normalizeAgentMode(agentMode),
				permissionMode: useSettingsStore.getState().permissionMode,
				multiAgent,
				reasoningEffort,
			});
			if (originActive) {
				if (textUnchanged) setValue('');
				if (removed.length > 0) setAttachments(remaining);
				if (textUnchanged || removed.length > 0) {
					requestAnimationFrame(() => {
						applyTaHeight(false);
						taRef.current?.focus();
					});
				}
			}
		for (const attachment of removed) {
			if (attachment.kind === 'image' && attachment.previewUrl.startsWith('blob:')) {
				URL.revokeObjectURL(attachment.previewUrl);
			}
		}
		};
			let clearedByCallback = false;
			const started = await sendMessage(
				payload.text,
				mediaRefs,
				[],
				agentMode,
				clearAfterAccept,
				multiAgent,
				{
					sessionId: sessionId ?? undefined,
					background: Boolean(sessionId && activeIdRef.current !== sessionId),
					reasoningEffort,
					steerIfBusy: mode === 'steer',
				},
			);
			const stillHere =
				sessionId != null &&
				chatUiStoreApi.getState().activeId === sessionId;
			if (!started) {
				sendAcceptPendingRef.current = false;
				const st = chatUiStoreApi.getState();
				if (sessionId && sessionStreamActive(st, sessionId)) {
					toast.info('当前会话正在生成，请先停止或稍候再试');
				}
				return;
			}
			if (!clearedByCallback) {
				clearAfterAccept();
			}
			if (stillHere) {
				requestAnimationFrame(() => {
					if (taRef.current) {
						taRef.current.style.height = `${TA_MIN_PX}px`;
						taRef.current.style.overflowY = 'hidden';
						taRef.current.focus();
					}
				});
			}
		})().catch(err => {
			sendAcceptPendingRef.current = false;
			toast.error(err instanceof Error ? err.message : String(err));
		});
	};

	const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
		// IME 组词中：确认键/方向键属于输入法，一律放行（修复组词上屏瞬间
		// Enter 直接发送半截输入的隐患；仲裁在 composing 期间同样放行）。
		if (e.nativeEvent.isComposing) {
			return;
		}
		// 弹层键盘仲裁（combobox 语义）：焦点始终留在编辑器表面，
		// ↑↓/Tab/Enter/Esc 先经纯函数核裁决，pass 才落到默认行为。
		if (popupOpen) {
			const KEY_MAP: Partial<Record<string, SlashMenuKey>> = {
				ArrowUp: 'up',
				ArrowDown: 'down',
				Enter: 'enter',
				Tab: 'tab',
				Escape: 'escape',
			};
			const menuKey = KEY_MAP[e.key];
			if (menuKey) {
				const verdict = arbitrateSlashMenuKey({
					key: menuKey,
					composing: false,
					highlight: slashHighlight,
					count: popupItems.length,
				});
				if (verdict.type === 'move') {
					e.preventDefault();
					setSlashHighlight(verdict.next);
					return;
				}
				if (verdict.type === 'pick') {
					e.preventDefault();
					const item = popupItems[verdict.index];
					if (item) {
						if (atToken) {
							applyAtPick(item.replacement);
						} else {
							applySlashPick(item.replacement);
						}
					}
					return;
				}
				if (verdict.type === 'close') {
					e.preventDefault();
					setSlashDismissed(true);
					return;
				}
				// pass：无高亮的 Enter 落到下方发送，Tab 归还焦点遍历。
			}
		}
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			// 忙时 Ctrl/Cmd+Enter = 引导（本轮下一个边界就投给模型）；
			// 裸 Enter 保持排队语义（既有行为不变）。
			onSend(
				resolveSendMode({
					streaming: currentSessionStreaming,
					modifier: e.ctrlKey || e.metaKey,
					enter: true,
				}),
			);
		}
	};

	return (
		<div className="shrink-0 px-3 pb-2.5 pt-1.5 sm:px-5 sm:pb-4">
			<div className="mx-auto w-full max-w-3xl">
				{slashExecuting ? (
					<p className="anim-fade mb-1.5 px-1 font-mono text-[11px] text-mute" role="status">
						正在执行 {slashExecutingName}… 草稿会保留
					</p>
				) : null}
				{remoteLoggedIn ? null : !apiKey.trim() &&
				!allowsEmptyApiKey(provider) &&
				!currentSessionStreaming ? (
					<p className="mb-1.5 px-1 font-sans text-[11px] text-mute">
						尚未配置 API Key。
						<button
							type="button"
							className="ml-1 text-accent underline-offset-2 hover:underline"
							onClick={() => openSettings()}
						>
							打开设置
						</button>
					</p>
				) : null}
				{currentSessionStreaming && (
					<p className="anim-fade mb-1.5 px-1 font-mono text-[11px] text-mute">
						<span className="xy-thinking">
							{statusText || 'thinking…'}
						</span>
						<span className="mx-2 text-line">·</span>
						Esc 中断
						{steerHintVisible(currentSessionStreaming) ? (
							<>
								<span className="mx-2 text-line">·</span>
								Ctrl+Enter 引导本回合
							</>
						) : null}
					</p>
				)}
				{!currentSessionStreaming &&
				statusText === '已停止' &&
				!remoteLoggedIn ? (
					<p className="anim-fade mb-1.5 px-1">
						<button
							type="button"
							className="xy-press rounded-md border border-line/70 bg-paper px-2.5 py-1 font-sans text-[12px] text-ink hover:bg-paper-deep/50"
							onClick={() => {
								void sendMessage('继续').then(accepted => {
									if (!accepted) toast.info('继续请求未被接受，请查看会话提示');
								}).catch(error => {
									toast.error(error instanceof Error ? error.message : String(error));
								});
							}}
						>
							继续未完成任务
						</button>
					</p>
				) : null}

				<div className="mb-1.5">
					<ErrorBanner embedded />
				</div>

				<div className="xy-composer-dock">
				{activeSessionArchived ? (
					<div
						role="status"
						className="flex items-center justify-between gap-3 border-b border-line/40 px-3 py-2 text-xs text-mute"
					>
						<span>此对话已归档，恢复后才能发送或编辑。</span>
						<button
							type="button"
							className="shrink-0 rounded-md px-2 py-1 font-medium text-accent hover:bg-accent/10"
							onClick={() => {
								if (!activeId) return;
								void restoreSession(activeId).catch(error =>
									toast.error(error instanceof Error ? error.message : '恢复失败'),
								);
							}}
						>
							恢复对话
						</button>
					</div>
				) : null}
				<div
					className={cn(
						isComposerFused && 'xy-composer-stack',
						isComposerFused && dragOver && 'is-drag-over',
					)}
				>
				{showTodoDock ? <SessionTodoDock embedded /> : null}
				{goalDockLive ? <SessionGoalDock embedded /> : null}
				{hasInboxChip && inboxItems.length > 0 ? (
					// 排队列表：全部条目可见（默认 3 条，超出折叠）——
					// 每条独立行：状态、文本与安全可用的编辑/重试/取消动作。
					// delivering / syncing 行不可编辑/取消（后端 409，前端先行拦截）。
					<div className="xy-queue-dock" data-queue-dock="">
						{manualQueueResumeAvailable ? (
							<div className="flex items-center justify-between gap-3 border-b border-line/40 px-3 py-2 text-xs text-mute">
								<span>自动投递已暂停</span>
								<button
									type="button"
									className="shrink-0 rounded-md px-2 py-1 font-medium text-accent hover:bg-accent/10 disabled:opacity-50"
									disabled={activeSessionArchived || queueActionsInFlight.has('__resume_queued__')}
									title={activeSessionArchived ? '归档对话不能继续投递，请先恢复' : undefined}
									onClick={() => {
										if (!activeId || activeSessionArchived) return;
										const sessionId = activeId;
										const current = chatUiStoreApi.getState();
										if (
											current.sessions.some(
												session => session.id === sessionId && session.archived,
											)
										) return;
										const backendId = activeBackendSessionId(current.historyById, sessionId);
										void runQueueAction(
											'__resume_queued__',
											() => resumeInbox(backendId),
											'继续投递失败',
										).then(() => refreshInbox(sessionId));
									}}
								>
									继续投递
								</button>
							</div>
						) : null}
						{visibleInbox.map(it => {
							const isEditing = editingId === it.queue_id;
							const statusLabel =
								it.state === 'syncing'
									? '同步回复'
									: it.state === 'delivering'
										? '投递中'
										: it.state === 'stuck'
											? '需重试'
											: '排队';
							const queuePositionLabel = it.state === 'queued'
								? ` · 第 ${it.position} 位`
								: '';
							const statusClass = cn(
								'shrink-0 text-[10px]',
								it.state === 'delivering' || it.state === 'syncing'
									? 'text-accent'
									: it.state === 'stuck'
										? 'text-danger'
										: 'text-mute',
							);
							return (
								<div className="xy-queue-card" key={it.queue_id}>
									<span className="xy-queue-grip" aria-hidden>
										<GripVertical className="h-3.5 w-3.5" strokeWidth={1.9} />
									</span>
									{isEditing ? (
										<input
											value={queueDraft}
											onChange={e => setQueueDraft(e.target.value)}
											onKeyDown={e => {
												if (e.key === 'Enter') saveQueueEdit();
												if (e.key === 'Escape') {
													// 先立旗再关闭：拦住随后的失焦保存，避免 Esc 误保存。
													queueEscRef.current = true;
													closeQueueEdit();
												}
											}}
											onBlur={saveQueueEdit}
											autoFocus
											maxLength={2000}
											aria-label="编辑排队消息"
											className="min-w-0 flex-1 rounded-md border border-line/70 bg-paper-deep/40 px-2 py-0.5 text-[12.5px] text-ink outline-none focus:border-accent/60"
										/>
									) : (
										<span
											className="xy-queue-text"
											data-stuck={it.state === 'stuck' ? '' : undefined}
										>
											{it.text}
										</span>
									)}
									<span
										className={statusClass}
										title={
											it.state === 'queued'
												? `队列位置 ${it.position}`
												: undefined
										}
									>
										{statusLabel}{queuePositionLabel}
									</span>
									<div className="xy-queue-actions" hidden={isEditing}>
										{canMutateInboxItem(it.state) ? (
											<button
												type="button"
												className="xy-queue-action disabled:pointer-events-none disabled:opacity-40"
												title={activeSessionArchived ? '归档对话只读，请先恢复' : '编辑消息'}
												disabled={activeSessionArchived || queueActionsInFlight.has(it.queue_id)}
												onClick={() => openQueueEdit(it)}
											>
												<Pencil className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
											</button>
										) : null}
										{it.state === 'stuck' ? (
											<button
												type="button"
												className="xy-queue-action disabled:pointer-events-none disabled:opacity-40"
												title={
													queueActionsInFlight.has(it.queue_id)
														? '正在重新投递…'
														: activeSessionArchived
															? '归档对话不能启动新的投递，请先恢复'
															: '重新投递'
												}
												disabled={activeSessionArchived || queueActionsInFlight.has(it.queue_id)}
												onClick={() => {
													const sessionId = activeId;
													if (!sessionId || activeSessionArchived) return;
													const current = chatUiStoreApi.getState();
													if (
														current.sessions.some(
															session => session.id === sessionId && session.archived,
														)
													) return;
													const backendId = activeBackendSessionId(current.historyById, sessionId);
													void runQueueAction(
														it.queue_id,
														() => resumeInbox(backendId, it.queue_id),
														'重新投递失败',
													).then(() => refreshInbox(sessionId));
												}}
											>
												<Send className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
											</button>
										) : null}
										<button
											type="button"
											className="xy-queue-action disabled:pointer-events-none disabled:opacity-40"
											title={
												activeSessionArchived
													? '归档对话只读，请先恢复'
													: it.state === 'syncing'
														? '等待同步服务端回复'
														: it.state === 'delivering'
															? '已开始投递，无法取消'
															: queueActionsInFlight.has(it.queue_id)
																? '正在处理…'
																: '取消排队'
											}
											disabled={
												activeSessionArchived ||
												!canMutateInboxItem(it.state) ||
												queueActionsInFlight.has(it.queue_id)
											}
											onClick={() => cancelQueueItem(it)}
										>
											<X className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
										</button>
									</div>
								</div>
							);
						})}
						{hiddenInboxCount > 0 ? (
							<button
								type="button"
								className="xy-queue-more"
								onClick={() => setQueueExpanded(true)}
							>
								展开其余 {hiddenInboxCount} 条
							</button>
						) : null}
						{queueExpanded && hiddenInboxCount === 0 && inboxItems.length > QUEUE_PREVIEW_COUNT ? (
							<button
								type="button"
								className="xy-queue-more"
								onClick={() => setQueueExpanded(false)}
							>
								收起排队列表
							</button>
						) : null}
					</div>
				) : null}
				<PermissionDialog />
				<AskUserDialog />
				<PlanDialog />

				<div className={cn(isComposerFused && 'xy-composer-fused-slot')}>
				<div
					onDragEnter={e => {
						if (remoteLoggedIn) {
							return;
						}
						e.preventDefault();
						setDragOver(true);
					}}
					onDragOver={e => {
						if (remoteLoggedIn) {
							return;
						}
						e.preventDefault();
						setDragOver(true);
					}}
					onDragLeave={e => {
						e.preventDefault();
						if (e.currentTarget.contains(e.relatedTarget as Node)) {
							return;
						}
						setDragOver(false);
					}}
					onDrop={e => {
						e.preventDefault();
						setDragOver(false);
						if (remoteLoggedIn) {
							return;
						}
						void onPickFiles(e.dataTransfer.files);
					}}
					className={cn(
						'xy-surface xy-composer-surface relative flex min-h-0 w-full flex-col',
						'transition-[border-color,box-shadow,border-radius] duration-200',
						isComposerFused
							? 'xy-composer-fused shrink-0'
							: 'xy-user-bubble rounded-2xl',
						!isComposerFused &&
							dragOver &&
							'!border-accent ring-2 ring-accent/20',
					)}
				>
					{images.length > 0 && !remoteLoggedIn && (
						<div className="flex flex-wrap gap-2 border-b border-line/40 px-3 pt-2.5 pb-2">
							{images.map(img => (
								<div
									key={img.id}
									className="anim-pop group relative h-14 w-14 overflow-hidden rounded-xl border border-line/70 bg-paper-deep/60"
								>
										<button
											type="button"
											title="点击查看原图"
											aria-label={`查看原图：${img.name}`}
											onClick={() => setPreviewImage(img)}
											className="absolute inset-0 z-0 cursor-zoom-in border-0 bg-transparent p-0"
										>
																									<img
															src={img.previewUrl}
															alt={img.name}
															className="h-full w-full object-cover"
															draggable={false}
														/>
														<span className="pointer-events-none absolute right-1 bottom-1 flex h-6 w-6 items-center justify-center rounded-full bg-ink/60 text-paper opacity-0 shadow-sm transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
															<ZoomIn className="h-3.5 w-3.5" strokeWidth={1.9} />
														</span>
													</button>

										<button
											type="button"
											aria-label={`移除 ${img.name}`}
											onClick={() => removeAttachment(img.id)}
											className="xy-icon-btn xy-hover-reveal absolute top-0.5 right-0.5 z-10 flex h-5 w-5 items-center justify-center rounded-full bg-ink/75 text-paper opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 hover:bg-ink"
										>
											<X className="h-3 w-3" />
										</button>
								</div>
							))}
						</div>
					)}

					{files.length > 0 && !remoteLoggedIn && (
						<div className="flex flex-wrap items-center gap-1.5 px-3 pt-2 pb-0.5">
							{files.map(a => (
								<span
									key={a.id}
									title={a.path || a.name}
									className="anim-pop group/filechip inline-flex max-w-[220px] items-center gap-1 rounded-md bg-accent/10 py-0.5 pr-1 pl-1.5 font-sans text-[12.5px] text-accent"
								>
									<span className="min-w-0 truncate font-medium">
										{a.name}
									</span>
									<button
										type="button"
										aria-label={`移除 ${a.name}`}
										onClick={() => removeAttachment(a.id)}
										className="xy-icon-btn flex h-4 w-4 shrink-0 items-center justify-center rounded text-accent/70 opacity-70 hover:bg-accent/15 hover:text-accent hover:opacity-100"
									>
										<X className="h-3 w-3" strokeWidth={2} />
									</button>
								</span>
							))}
						</div>
					)}

					{remoteLoggedIn ? (
						<div
							className="flex min-h-[96px] w-full items-center justify-center px-3 font-sans text-[14px] leading-8 text-mute"
							aria-label="远程已连接"
						>
							远程已连接
						</div>
					) : (
						<>
							<div className="relative flex w-full min-h-[36px] shrink-0">
								{slashMenuOpen ? (
									<div className="xy-menu-flyout anim-pop absolute bottom-full left-0 z-50 mb-1.5 w-[min(480px,100%)] overflow-hidden rounded-xl border border-line/50">
										<div
											ref={flyoutRef}
											role="listbox"
											aria-label="斜杠命令与技能建议"
											className="max-h-[320px] overflow-y-auto px-1.5 py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
										>
									{filteredSkills.length > 0 ? (
										<div className="flex items-center gap-1.5 px-2 pb-1 pt-2 xy-section-label">
											<span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent" />
											技能
										</div>
									) : null}
									{filteredSkills.map((s, i) => (
										<button
											key={`skill:${s.source}:${s.name}`}
											type="button"
											role="option"
											aria-selected={slashHighlight === i}
											style={{'--row-i': i} as CSSProperties}
											onMouseDown={e => e.preventDefault()}
											onMouseEnter={() => setSlashHighlight(i)}
											onClick={() => applySlashPick(`/${s.name} `)}
											className={cn(
												'xy-menu-row xy-flyout-row flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors duration-100',
												// scroll-mt：键盘滚到顶行时给上方分组头留位，防止「技能」头被裁掉。
												'scroll-mt-7',
												slashHighlight === i && 'bg-paper-deep/80',
											)}
										>
											<span className="min-w-0 flex-1 truncate font-mono text-[12.5px] font-medium text-ink">
												{s.name}
											</span>
											{s.description ? (
												<span className="max-w-[46%] truncate text-[11px] text-mute">
													{s.description}
												</span>
											) : null}
										</button>
									))}
									{slashSuggest.length > 0 && filteredSkills.length > 0 ? (
										<div aria-hidden className="mx-2 my-1.5 h-px bg-line/50" />
									) : null}
									{slashSuggest.length > 0 ? (
										<div className="flex items-center gap-1.5 px-2 pb-1 pt-2 xy-section-label">
											<span aria-hidden className="h-1.5 w-1.5 rounded-full bg-mute" />
											命令
										</div>
									) : null}
									{slashSuggest.map((c, i) => (
										<button
											key={c.name}
											type="button"
											role="option"
											aria-selected={slashHighlight === filteredSkills.length + i}
											style={{'--row-i': filteredSkills.length + i} as CSSProperties}
											onMouseDown={e => e.preventDefault()}
											onMouseEnter={() => setSlashHighlight(filteredSkills.length + i)}
											onClick={() => applySlashPick(`/${c.name} `)}
											className={cn(
												'xy-menu-row xy-flyout-row flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors duration-100',
												// scroll-mt：键盘滚到顶行时给上方分组头留位，防止「命令」头被裁掉。
												'scroll-mt-7',
												slashHighlight === filteredSkills.length + i && 'bg-paper-deep/80',
											)}
										>
											<span className="min-w-0 flex-1 truncate font-mono text-[12.5px] font-medium text-ink">
												{c.name}
											</span>
											{c.summary ? (
												<span className="max-w-[46%] truncate text-[11px] text-mute">
													{c.summary}
												</span>
											) : null}
										</button>
									))}
										</div>
										<div className="flex items-center justify-end gap-2.5 border-t border-line/40 px-2.5 py-1 text-[10.5px] text-mute">
											<span className="flex items-center gap-1">
												<span className="xy-menu-kbd">↑↓</span>选择
											</span>
											<span className="flex items-center gap-1">
												<span className="xy-menu-kbd">Tab</span>补全
											</span>
											<span className="flex items-center gap-1">
												<span className="xy-menu-kbd">Enter</span>确认
											</span>
										</div>
									</div>
								) : null}
								{atMenuOpen ? (
									<div
										ref={flyoutRef}
										role="listbox"
										aria-label="文件引用建议"
										className="xy-menu-flyout absolute bottom-full left-0 z-50 mb-1.5 max-h-[280px] w-[min(440px,100%)] overflow-y-auto rounded-xl border border-line/50 p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
									>
										<div className="px-1 pb-0.5 pt-1 xy-section-label">
											文件引用
										</div>
										{atFiles.map((f, i) => (
											<button
												key={`ref:${f}`}
												type="button"
												role="option"
												aria-selected={slashHighlight === i}
												onMouseDown={e => e.preventDefault()}
												onMouseEnter={() => setSlashHighlight(i)}
												onClick={() => applyAtPick(`@${f} `)}
												className={cn(
													'xy-menu-row flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left',
													slashHighlight === i && 'bg-paper-deep/70',
												)}
											>
												<span className="h-4 w-4 shrink-0 rounded-sm border border-line/70 text-center font-mono text-[10px] leading-4 text-mute">
													@
												</span>
												<span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink-soft">
													{f}
												</span>
											</button>
										))}
									</div>
								) : null}
								<textarea
									ref={taRef}
									value={value}
									onChange={e => {
										const next = e.target.value;
										const draftSessionId = activeIdRef.current ?? activeId;
										setValue(next, draftSessionId);
										setTaCaret(e.target.selectionStart ?? next.length);
										// 输入即写入当前会话草稿（防抖 250ms 落 localStorage）：
										// 不切会话 / 不发送 / 直接刷新时输入不丢。setComposerDraft
										// 为按字段合并，仅 text 变化，attachments/模式不受影响。
										if (draftSessionId) {
											setComposerDraft(draftSessionId, {
												text: next,
												attachments: attachmentsRef.current,
											});
										}
									}}
									onSelect={e => {
										// 方向键/点击/拖选移动光标:同步词元位置 + 方向(自绘光标跟 focus 端)
										setTaCaret(e.currentTarget.selectionStart ?? 0);
										setTaCaretDir(e.currentTarget.selectionDirection ?? 'forward');
									}}
									onKeyDown={onKeyDown}
									onPaste={onPaste}
									onCompositionStart={() => setImeComposing(true)}
									onCompositionEnd={() => setImeComposing(false)}
									onScroll={e => {
										caretApiRef.current?.reposition();
										void e.currentTarget.scrollTop;
									}}
									onFocus={() => {
										setSlashDismissed(false);
										setTaFocused(true);
									}}
									onBlur={() => {
										setSlashDismissed(true);
										setTaFocused(false);
									}}
									onContextMenu={(e: ReactMouseEvent<HTMLTextAreaElement>) => {
										const el = taRef.current;
										if (!el) {
											return;
										}
										showContextMenu(e, textFieldMenuItems(el), '编辑');
									}}
									rows={1}
									placeholder="描述任务… Enter 发送"
									className={cn(
										'min-h-[36px] w-full resize-none bg-transparent px-3 pt-3 text-left font-sans text-[14px] leading-6 text-ink outline-none transition-[height] duration-200 [transition-timing-function:var(--ease-out-soft)] placeholder:text-mute/65',
										/* 自绘光标接管显示:原文隐藏 + 原生 caret 透明(IME/超大文本自动回退),避免两层文字叠影 */
										caretOverlayActive && 'text-transparent [caret-color:transparent]',
									)}
								/>
								<TypingCaret
									value={value}
									caret={taCaret}
									caretDir={taCaretDir}
									colorRanges={caretColoring.ranges}
									ghostHint={caretColoring.hint}
									focused={taFocused}
									active={caretOverlayActive}
									apiRef={caretApiRef}
								/>
								{taCapped || taExpanded ? (
									<button
										type="button"
										aria-label={taExpanded ? '收起输入框' : '展开输入框'}
										title={taExpanded ? '收起输入框' : '展开输入框'}
										onMouseDown={e => e.preventDefault()}
										onClick={() => applyTaHeight(!taExpanded)}
										className="xy-press absolute right-0 top-1.5 z-10 flex h-[22px] w-[22px] items-center justify-center rounded-full text-mute transition-colors duration-150 hover:bg-paper-deep/60 hover:text-ink"
									>
										<svg
											width="20"
											height="20"
											viewBox="0 0 20 20"
											fill="none"
											aria-hidden
											className={cn(
												'-scale-x-100 transition-transform duration-200 [transition-timing-function:var(--ease-out-soft)]',
												taExpanded && 'rotate-180',
											)}
										>
											<path
												d="M4 13 A 9 9 0 0 1 13 4"
												fill="none"
												stroke="currentColor"
												strokeWidth="1.5"
												strokeLinecap="round"
											/>
										</svg>
									</button>
								) : null}
							</div>

							<input
								ref={fileRef}
								type="file"
								multiple
								accept="image/*,*/*"
								className="hidden"
								onChange={e => void onPickFiles(e.target.files)}
							/>

							<div className="flex items-center gap-2 px-2 pb-2 pt-1">
								<div ref={quickMenuRef} className="relative shrink-0">
									<button
										type="button"
										aria-label="打开操作菜单"
										aria-haspopup="menu"
										aria-expanded={quickMenuOpen}
										aria-controls={quickMenuId}
										disabled={uploading}
										onClick={() => {
											setMcpOpen(false);
											setQuickMenuOpen(v => !v);
										}}
										className={cn(
											'xy-icon-btn flex h-8 w-8 items-center justify-center rounded-full text-mute hover:bg-paper-deep hover:text-ink disabled:opacity-40',
											quickMenuOpen && 'bg-paper-deep text-ink',
										)}
									>
										<Plus className="h-4 w-4" strokeWidth={2} />
									</button>

									{quickMenuOpen ? (
										<ComposerQuickMenu
											open={quickMenuOpen}
											menuId={quickMenuId}
											agentMode={agentMode}
											multiAgent={multiAgent}
											uploading={uploading}
											onSelectMode={m => {
												setQuickMenuOpen(false);
												setAgentMode(m);
											}}
											onToggleMultiAgent={() => {
												setQuickMenuOpen(false);
												setMultiAgent(v => !v);
											}}
											onAddFile={() => {
												setQuickMenuOpen(false);
												fileRef.current?.click();
											}}
											onRunMcp={() => {
												setQuickMenuOpen(false);
												// smoke-test #8：+ 菜单 MCP 入口 → 打开 MCP 面板
												//（搜索/工具勾选/启停/批准/Manage）。
												setMcpOpen(v => !v);
											}}
										/>
									) : null}
								</div>

								<McpPanel open={mcpOpen} onClose={() => setMcpOpen(false)} />

								<ModeChip />
								{multiAgent && <MultiAgentChip onExit={() => setMultiAgent(false)} />}
								<ApprovalModeButton />
								<div className="flex-1" />
								<div className="flex min-h-8 min-w-0 shrink-0 flex-wrap items-center gap-1">
									<div ref={modelMenuRef} className="relative hidden sm:block">
										<button
											type="button"
											aria-haspopup="listbox"
											aria-expanded={modelOpen}
											aria-controls={modelMenuId}
											onClick={() => setModelOpen(v => !v)}
											className={cn(
												'inline-flex h-7 max-w-[9.5rem] items-center gap-1 rounded-full px-2 font-mono text-[11px] leading-none text-mute',
												'hover:bg-ink/[0.06] hover:text-ink disabled:opacity-40',
												modelOpen && 'bg-ink/[0.08] text-ink',
											)}
										>
											<span className="truncate">{model}</span>
											<ChevronDown
												className={cn(
													'h-3 w-3 shrink-0 opacity-50 transition-transform',
													modelOpen && 'rotate-180 opacity-70',
												)}
											/>
										</button>
										<ModelPicker
											open={modelOpen}
											menuId={modelMenuId}
											reasoningEffort={reasoningEffort}
											onReasoningEffortChange={setReasoningEffort}
										/>
									</div>
									<SendStopButton
										streaming={currentSessionStreaming}
										canSend={canSend}
										smoothness={smoothness}
										onSend={onSend}
										onStop={() => void stopGeneration()}
									/>
								</div>
							</div>
						</>
					)}

					{dragOver ? (
						<div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-[inherit] bg-accent/8 font-mono text-xs text-accent">
							松开以添加图片 / 文件
						</div>
					) : null}
				</div>
				</div>
				</div>
				</div>
			</div>
					<ImageReaderDialog
				image={
					previewImage
						? {
								src: previewImage.previewUrl,
								alt: previewImage.name,
								title: `原图预览：${previewImage.name}`,
							}
						: null
				}
				onClose={() => setPreviewImage(null)}
			/>

		</div>
	);
}
