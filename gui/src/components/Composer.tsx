import {
	ArrowUp,
	ChevronDown,
	Network,
	Plus,
	Square,
	X,
} from 'lucide-react';
import {
	useEffect,
	useId,
	useMemo,
	useRef,
	useState,
	type ClipboardEvent,
	type CSSProperties,
	type KeyboardEvent,
	type MouseEvent as ReactMouseEvent,
} from 'react';
import {fetchFileReferences, fetchSkills, uploadFile, uploadMedia, resumeInbox, type SkillInfo} from '@/lib/api';
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
import {handleComposerSlash, lastUserText} from '@/lib/slashCommands';
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

type FileAttachment = DraftFileAttachment;
type ImageAttachment = DraftImageAttachment;
type Attachment = DraftAttachment;

const MAX_IMAGES = 8;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
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
					onClick={onSend}
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
			onClick={showStop ? onStop : onSend}
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
	const [value, setValue] = useState('');
	const [attachments, setAttachments] = useState<Attachment[]>([]);
	const [uploading, setUploading] = useState(false);
	const [dragOver, setDragOver] = useState(false);
	const fileRef = useRef<HTMLInputElement>(null);
	const taRef = useRef<HTMLTextAreaElement>(null);
	const attachmentsRef = useRef(attachments);
	attachmentsRef.current = attachments;
	const activeId = useChatUiStore(s => s.activeId);
	const statusText = useChatUiStore(
		s => selectActiveSessionStream(s).statusText,
	);
	const sendMessage = useChatUiStore(s => s.sendMessage);
	const chatUiStoreApi = useChatUiStoreApi();
	const stopGeneration = useChatUiStore(s => s.stopGeneration);
	const composerInsertSeq = useChatUiStore(s => s.composerInsertSeq);
	const composerFocusSeq = useChatUiStore(s => s.composerFocusSeq);
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
	/** smoke-test #8：+ 菜单里的 MCP 面板（参考图：搜索 + Manage + 空态）。 */
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
	const hasInboxChip = useChatUiStore(s => s.hasInboxChip);
	const refreshInbox = useChatUiStore(s => s.refreshInbox);
	const cancelInboxItem = useChatUiStore(s => s.cancelInboxItem);
	const inboxItems: InboxQueuedItem[] = (activeId ? inboxBySession[activeId] : undefined) ?? [];
	// P1：chip 可见时 2s 轮询排队队列（多端一致；队空 = 已投递/取消 → 清 chip）。
	useEffect(() => {
		if (!hasInboxChip || !activeId) {
			return;
		}
		const tick = () => {
			void refreshInbox(activeId);
		};
		tick();
		const t = setInterval(tick, 2000);
		return () => clearInterval(t);
	}, [hasInboxChip, activeId, refreshInbox]);
	const [taCapped, setTaCapped] = useState(false);
	const [taExpanded, setTaExpanded] = useState(false);
	/** 光标位置：slash 弹层按「光标处词元」判定，支持消息中途输入 / 唤起。 */
	const [taCaret, setTaCaret] = useState(0);
	/** Esc / 点击外部临时关闭弹层；输入变化后自动恢复。 */
	const [slashDismissed, setSlashDismissed] = useState(false);
	/** 弹层键盘高亮（扁平列表下标：技能组在前、命令组在后）；hover 与键盘共用。 */
	const [slashHighlight, setSlashHighlight] = useState<number | null>(null);
	/** IME 组词期间关闭着色覆盖层，避免合成文字被 text-transparent 隐藏。 */
	const [imeComposing, setImeComposing] = useState(false);
	/** 当前工作区技能清单（/ 弹层与着色候选；按 workspace 缓存）。 */
	const [slashSkills, setSlashSkills] = useState<SkillInfo[]>([]);
	const taExpandedRef = useRef(false);
	const modelMenuRef = useRef<HTMLDivElement>(null);
	const quickMenuRef = useRef<HTMLDivElement>(null);
	const modelMenuId = useId();
	const quickMenuId = useId();
	/** 点选候选项后待应用的光标位置（等 DOM value 提交后再 setSelectionRange）。 */
	const pendingCaretRef = useRef<number | null>(null);
	/** slash 着色覆盖层（镜像 textarea 文本，给 /词元 上色）。 */
	const slashOverlayRef = useRef<HTMLDivElement>(null);
	/** 技能清单缓存：workspace → skills。 */
	const slashSkillsRef = useRef<Record<string, SkillInfo[]>>({});
	const activeIdRef = useRef(activeId);
	const valueRef = useRef(value);
	valueRef.current = value;
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
	useEffect(() => {
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
		setValue(loaded.text);
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

	// 统一斜杠命令：由「光标处 slash 词元」驱动候选与技能弹层（来自生成的 manifest）。
	// / 不在行首时（如消息中途「帮我 /xxx」）同样生效；删除 / 后词元消失，弹层随之收起。
	const activeWorkspace = useChatStore(
		s => s.spaces.find(sp => sp.id === s.activeSpaceId)?.rootPath ?? '',
	);
	const slashToken = useMemo(() => slashTokenAt(value, taCaret), [value, taCaret]);
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
	const [atFiles, setAtFiles] = useState<string[]>([]);
	const [atLoaded, setAtLoaded] = useState(false);
	useEffect(() => {
		if (!atToken) {
			setAtLoaded(false);
			return;
		}
		if (!activeWorkspace) {
			return;
		}
		const controller = new AbortController();
		const t = setTimeout(() => {
			void fetchFileReferences(activeWorkspace, atQuery, controller.signal).then(report => {
				if (controller.signal.aborted || !report) {
					return;
				}
				setAtFiles(report.files);
				setAtLoaded(true);
			});
		}, 120);
		return () => {
			controller.abort();
			clearTimeout(t);
		};
	}, [atToken, atQuery, activeWorkspace]);
	const atMenuOpen =
		atToken !== null &&
		!slashDismissed &&
		atLoaded &&
		atFiles.length > 0;

	// 光标处于 slash 词元、或输入以 / 开头（着色需要）时，拉取当前工作区的技能清单。
	const slashZone = slashIntent || value.startsWith('/');
	useEffect(() => {
		if (!slashZone) {
			return;
		}
		const cached = slashSkillsRef.current[activeWorkspace];
		if (cached && cached.length > 0) {
			// 仅非空缓存可短路：写入端已不缓存空结果，这里再设读取端防线，
			// 兜住 HMR/热更新残留的陈旧空数组（react-refresh 保留 useRef 状态）。
			setSlashSkills(cached);
			return;
		}
		let cancelled = false;
		void fetchSkills(activeWorkspace).then(report => {
			if (cancelled || !report || report.ok === false) {
				return; // 失败不缓存：下次唤起弹层重试。
			}
			// 仅非空结果写缓存：空结果（server 首启/工作区切换瞬间）不上缓存位，
			// 否则 truthy 空数组会让后续 slashZone 永久短路，技能从此消失。
			if (report.skills.length > 0) {
				slashSkillsRef.current[activeWorkspace] = report.skills;
			}
			setSlashSkills(report.skills);
		});
		return () => {
			cancelled = true;
		};
	}, [slashZone, activeWorkspace]);

	// 技能候选按词元关键词过滤（名称包含即可），空词元展示全部。
	const filteredSkills = useMemo(() => {
		if (!slashQuery) {
			return slashSkills;
		}
		return slashSkills.filter(s => s.name.toLowerCase().includes(slashQuery));
	}, [slashSkills, slashQuery]);

	// 弹层只在光标位于 slash 词元时出现；此前 slashSkills 残留导致删除 / 后关不掉。
	const slashMenuOpen =
		slashIntent &&
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

	// 高亮行自动滚入可视区（dsh combobox 语义）：键盘 ↑↓ 走出视口时列表跟随，
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

	// slash 着色覆盖层：/词元 命中命令 → 橙、命中技能 → 蓝（前缀也算，输入中即着色）。
	// URL（https://…）、路径（src/foo）整体是一个非空白词元，不以 / 开头，不会误着色。
	// ghost hint（claim hint 语义）：首词元精确命中命令/技能且参数空白时，
	// 在词元后展示灰字提示（零 DOM 侵入草稿，仅覆盖层显示，不参与提交）。
	const slashOverlay = useMemo(() => {
		if (imeComposing || !value.includes('/')) {
			return null;
		}
		const parts = value.split(/(\s+)/);
		let colored = false;
		const nodes = parts.map((part, i) => {
			if (part && part.startsWith('/') && part.length > 1) {
				const color = slashLeadingColor(part.slice(1), slashSkills);
				if (color) {
					colored = true;
					// 强调色统一走主题 accent token（黑白基调主题下与整体同相）。
					return (
						<span key={i} className="text-accent">
							{part}
						</span>
					);
				}
			}
			return part;
		});
		const ghostHint = slashGhostHint(value, slashSkills);
		if (ghostHint) {
			nodes.push(
				<span key="__ghost_hint" className="select-none text-ink/40">
					{ghostHint}
				</span>,
			);
		}
		return colored || ghostHint ? nodes : null;
	}, [value, slashSkills, imeComposing]);

	// 覆盖层接管显示时隐藏 textarea 原文，只留光标，避免两层文字叠影。
	const slashColoring = slashOverlay !== null;

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
		const el = taRef.current;
		if (!el || taExpandedRef.current) {
			return;
		}
		el.style.height = 'auto';
		const measured = el.scrollHeight;
		setTaCapped(measured >= TA_MAX_PX);
		const next = Math.min(TA_MAX_PX, Math.max(TA_MIN_PX, measured));
		el.style.height = `${next}px`;
		el.style.overflowY = measured > TA_MAX_PX ? 'auto' : 'hidden';
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

	const removeAttachment = (id: string) => {
		setAttachments(prev => {
			const target = prev.find(a => a.id === id);
			if (target?.kind === 'image') {
				URL.revokeObjectURL(target.previewUrl);
			}
			return prev.filter(a => a.id !== id);
		});
	};

	const clearAttachments = () => {
		setAttachments(prev => {
			for (const a of prev) {
				if (a.kind === 'image') {
					URL.revokeObjectURL(a.previewUrl);
				}
			}
			return [];
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
		const arr = Array.from(fileList);
		const imgs = arr.filter(f => f.type.startsWith('image/'));
		const others = arr.filter(f => !f.type.startsWith('image/'));
		if (imgs.length && !remoteLoggedIn) {
			addImages(imgs);
		}
		for (const file of others) {
			setUploading(true);
			try {
				const res = await uploadFile(file);
				const body = res.text ?? '';
				const MAX_UPLOAD_SNIPPET = 48_000;
				if (body.length > MAX_UPLOAD_SNIPPET) {
					toast.warn(
						`${res.filename || file.name} 较大，已按文件名引用（不内联全文）`,
					);
					setAttachments(prev => [
						...prev,
						{
							kind: 'file',
							id: uid('file'),
							name: res.filename || file.name,
							path: res.filename || file.name,
						},
					]);
				} else {
					setAttachments(prev => [
						...prev,
						{
							kind: 'file',
							id: uid('file'),
							name: res.filename || file.name,
							text: body,
						},
					]);
				}
			} catch (err) {
				toast.error(err instanceof Error ? err.message : String(err));
				return;
			} finally {
				setUploading(false);
			}
		}
		if (fileRef.current) {
			fileRef.current.value = '';
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

	const buildPayload = () => {
		const parts = [value.trim()];
		for (const a of files) {
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
		return {
			text: parts.join('').trim() || (images.length > 0 ? '请分析这些图片。' : ''),
			mediaRefs: images.flatMap(image => (image.mediaRef ? [image.mediaRef] : [])),
		};
	};

	const ensureMediaRefs = async (): Promise<string[]> => {
		const refs: string[] = [];
		for (const image of images) {
			if (image.mediaRef) {
				refs.push(image.mediaRef);
				continue;
			}
			if (!image.file) {
				throw new Error(`图片 ${image.name} 尚未准备好，请重新添加`);
			}
			const uploaded = await uploadMedia(image.file);
			refs.push(uploaded.media_ref);
			setAttachments(prev =>
				prev.map(item =>
					item.id === image.id && item.kind === 'image'
						? {...item, mediaRef: uploaded.media_ref}
						: item,
				),
			);
		}
		return refs;
	};

	const canSend =
		!remoteLoggedIn && !uploading && (Boolean(value.trim()) || attachments.length > 0);

	const onSend = () => {
		// 斜杠命令网关：/xxx 先在本机（本地命令/技能直呼/未知命令提示）或
		// POST /v1/slash（server 命令）执行。命中则拦截，不当作普通消息发给模型
		// （修复 /export、/map、/run、/mode 等在 GUI 主输入框被当作普通文本发送）。
		// 非斜杠输入由 parseSlashInput 判 not-slash → consumed=false，走正常发送。
		const valueTrim = value.trim();
		if (valueTrim.startsWith('/')) {
			const sessId = activeId ?? '';
			const st = useChatStore.getState();
			void (async () => {
				const consumed = await handleComposerSlash(valueTrim, {
					sessionId: sessId,
					backendSessionId:
						activeBackendSessionId(st.historyById, sessId) || undefined,
					workspace: activeWorkspace,
					onNewSession: () => {
						void st.createSession();
					},
					onRetryLast: () => {
						const last = lastUserText(sessId);
						if (last) {
							void st.sendMessage(last);
						} else {
							toast.info('还没有可重试的消息');
						}
					},
				});
				if (consumed) {
					setValue('');
					clearAttachments();
					requestAnimationFrame(() => {
						applyTaHeight(false);
						taRef.current?.focus();
					});
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
		const draftAttachments = attachments;
		// 仅在 store 接受消息后清除（乐观 UI 已落地）。
		void (async () => {
			let mediaRefs: string[];
			try {
				setUploading(true);
				mediaRefs = await ensureMediaRefs();
		} catch (err) {
			toast.error(err instanceof Error ? err.message : String(err));
			return;
		} finally {
			setUploading(false);
		}
			const clearAfterAccept = () => {
				if (clearedByCallback) {
					return;
				}
				clearedByCallback = true;
				const acceptedSessionId = sessionId ?? chatUiStoreApi.getState().activeId;
				if (!acceptedSessionId) {
					return;
				}
				setComposerDraft(acceptedSessionId, {
					text: '',
					attachments: [],
					agentMode: normalizeAgentMode(
						chatUiStoreApi.getState().agentMode,
					),
					permissionMode: useSettingsStore.getState().permissionMode,
					multiAgent: multiAgentRef.current,
					reasoningEffort: reasoningEffortRef.current,
				});
				setValue('');
				clearAttachments();
				requestAnimationFrame(() => {
					applyTaHeight(false);
					taRef.current?.focus();
				});
			};
			let clearedByCallback = false;
			const started = await sendMessage(
				payload.text,
				mediaRefs,
				[],
				agentMode,
				clearAfterAccept,
				multiAgent,
				{reasoningEffort},
			);
			const stillHere =
				sessionId != null &&
				chatUiStoreApi.getState().activeId === sessionId;
			if (!started) {
				if (sessionId) {
					setComposerDraft(sessionId, {
						text: draftText,
						attachments: draftAttachments,
					});
				}
				if (stillHere) {
					setValue(draftText);
					setAttachments(draftAttachments);
				}
				const st = chatUiStoreApi.getState();
				if (st.activeId && sessionStreamActive(st, st.activeId)) {
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
		})();
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
			onSend();
		}
	};

	return (
		<div className="shrink-0 px-3 pb-2.5 pt-1.5 sm:px-5 sm:pb-4">
			<div className="mx-auto w-full max-w-3xl">
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
								void sendMessage('继续');
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
				<div
					className={cn(
						isComposerFused && 'xy-composer-stack',
						isComposerFused && dragOver && 'is-drag-over',
					)}
				>
				{showTodoDock ? <SessionTodoDock embedded /> : null}
				{goalDockLive ? <SessionGoalDock embedded /> : null}
				{hasInboxChip && inboxItems.length > 0 ? (
					// 排队停靠条（对齐 dsh QueueDock：附着在输入卡顶部的队列面板，
					// 行高/发丝分隔/圆形图标动作同族；XEYO 差异：不做折叠头、
					// mono 序号直读位置、stuck 态 warn token 内联重试）。
					<ul
						role="list"
						aria-label="排队消息"
						className={cn(
							'max-h-[180px] overflow-y-auto overscroll-contain',
							'[&>li+li]:border-t [&>li+li]:border-line/60',
							isComposerFused
								? 'border-none bg-transparent'
								: 'mb-1.5 rounded-xl border border-line/70 bg-paper-deep/30',
						)}
					>
						{inboxItems.map((it, i) => {
							const stuck = it.state === 'stuck';
							return (
								<li
									key={it.queue_id || i}
									className="flex h-[34px] shrink-0 items-center gap-2.5 pr-1.5 pl-3"
								>
									<span
										aria-hidden
										className="shrink-0 font-mono text-[11px] tabular-nums text-mute"
									>
										#{it.position && it.position > 0 ? it.position : i + 1}
									</span>
									<span
										className={cn(
											'min-w-0 flex-1 truncate text-[12.5px]',
											stuck ? 'text-warn' : 'text-ink-soft',
										)}
									>
										{stuck ? `投递失败：${it.text}` : it.text}
									</span>
									{stuck ? (
										<button
											type="button"
											title="重新投递"
											onClick={() => {
												void resumeInbox(activeId ?? '');
												void refreshInbox(activeId ?? '');
											}}
											className="xy-press shrink-0 rounded-full px-1.5 py-0.5 font-sans text-[11px] text-warn hover:bg-warn/10"
										>
											重试
										</button>
									) : null}
									<button
										type="button"
										title="取消排队"
										onClick={() => {
											void cancelInboxItem(activeId ?? '', it.queue_id);
										}}
										className="xy-icon-btn inline-flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full text-mute transition-colors hover:bg-ink/5 hover:text-ink"
									>
										<X className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
									</button>
								</li>
							);
						})}
					</ul>
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
										<div className="flex items-center gap-1.5 px-2 pb-1 pt-2 text-[10px] font-medium uppercase tracking-[0.08em] text-mute">
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
										<div className="flex items-center gap-1.5 px-2 pb-1 pt-2 text-[10px] font-medium uppercase tracking-[0.08em] text-mute">
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
										<div className="px-1 pb-0.5 pt-1 text-[10px] font-medium uppercase tracking-[0.08em] text-mute">
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
												<span className="h-4 w-4 shrink-0 rounded-sm border border-line/70 text-center font-mono text-[9px] leading-4 text-mute">
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
										setValue(e.target.value);
										setTaCaret(e.target.selectionStart ?? e.target.value.length);
									}}
									onSelect={e => {
										// 方向键/点击移动光标时同步词元位置
										setTaCaret(e.currentTarget.selectionStart ?? 0);
									}}
									onKeyDown={onKeyDown}
									onPaste={onPaste}
									onCompositionStart={() => setImeComposing(true)}
									onCompositionEnd={() => setImeComposing(false)}
									onScroll={e => {
										if (slashOverlayRef.current) {
											slashOverlayRef.current.scrollTop =
												e.currentTarget.scrollTop;
										}
									}}
									onFocus={() => setSlashDismissed(false)}
									onBlur={() => setSlashDismissed(true)}
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
										/* 着色层接管显示时隐藏原文，只留可见光标，避免两层文字叠影 */
										slashColoring && 'text-transparent caret-accent',
									)}
								/>
								{slashColoring ? (
									<div
										ref={slashOverlayRef}
										aria-hidden
										className="pointer-events-none absolute inset-0 z-[4] overflow-hidden whitespace-pre-wrap break-words px-3 pt-3 font-sans text-[14px] leading-6 text-ink"
									>
										{slashOverlay}
									</div>
								) : null}
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
												//（搜索/工具勾选/启停/批准/Manage；参考图样式）。
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
