/**
 * Editing cluster extracted from messageList/MessageList.tsx.
 * Behavior unchanged: sticky edit refs, layout effects, begin/cancel/submit,
 * and the pinned-chip click-to-edit wiring. Edit submit opens rewindV3Store dialog.
 */
import {
	useCallback,
	useEffect,
	useId,
	useLayoutEffect,
	useRef,
	useState,
	type RefObject,
	type MutableRefObject,
	type MouseEvent,
} from 'react';
import {flushSync} from 'react-dom';
import {
	cancelFrameTask,
} from '@/lib/frameScheduler';
import {
	useMessageListRollbackStore,
} from '@/hooks/useMessageListStore';
import {useRewindV3Store} from '@/stores/rewindV3Store';
import {toast} from '@/lib/toast';
import {uid} from '@/lib/utils';
import {uploadFile} from '@/lib/api';
import type {ChatMessage} from '@/lib/types';
import type {DraftAttachment} from '@/lib/composerDrafts';
import {PROMPT_CHIP_MAX_PX} from '../sticky';
import type {StickyPromptController} from '../sticky/StickyPromptController';

type FrameKeys = {
	scroll: string;
	topFade: string;
	rail: string;
	stuck: string;
};

export type UseMessageListEditingOptions = {
	scrollerRef: RefObject<HTMLDivElement | null>;
	pinOverlayRef: RefObject<HTMLDivElement | null>;
	messagesRef: MutableRefObject<ChatMessage[]>;
	frameKeysRef: RefObject<FrameKeys | null>;
	stickyCtrl: StickyPromptController;
	flushStuck: () => void;
	requestStuckRef: RefObject<() => void>;
	muteStickyLayoutSnap: () => void;
	beginStickyEdit: (message: {id: string; text: string}) => {
		usedPortal: boolean;
		scrollTop: number | null;
		placeholderHeight: number;
	};
	endStickyEdit: () => void;
	setStickyEditingId: (id: string | null) => void;
	scheduleTopFade: () => void;
	editingViewportLockRef: MutableRefObject<boolean>;
	stickToBottom: MutableRefObject<boolean>;
	scrollScheduled: MutableRefObject<boolean>;
	hasRows: boolean;
	anyStreaming: boolean;
	messages: ChatMessage[];
	streamingText: string;
	isLoading: boolean;
	reasoningText: string;
	roundSignature: string;
	agentTasksPinKey: string;
	activeId: string | null;
};

export type UseMessageListEditingResult = {
	editingMessageId: string | null;
	editingText: string;
	setEditingText: (text: string) => void;
	editingCaret: number | null;
	editingSubmitting: boolean;
	editingUploading: boolean;
	editingAttachments: DraftAttachment[];
	editingExistingMediaRefs: string[];
	editFlowHeight: number;
	editClosing: boolean;
	modelOpen: boolean;
	modelMenuId: string;
	editRootRef: RefObject<HTMLDivElement | null>;
	promptEditRef: RefObject<HTMLDivElement | null>;
	editingTextareaRef: MutableRefObject<HTMLTextAreaElement | null>;
	editingFilePickerOpenRef: MutableRefObject<boolean>;
	editingFileInputRef: MutableRefObject<HTMLInputElement | null>;
	editModelMenuRef: MutableRefObject<HTMLDivElement | null>;
	stickyEditFlowLockRef: MutableRefObject<boolean>;
	beginEdit: (
		message: Pick<ChatMessage, 'id' | 'text' | 'mediaRefs'>,
		event?: MouseEvent<HTMLDivElement>,
	) => void;
	cancelEdit: () => void;
	submitEdit: () => Promise<void>;
	toggleModel: () => void;
	closeModel: () => void;
	onEditAttachmentPick: (files: FileList | File[] | null) => Promise<void>;
	onRemoveEditAttachment: (id: string) => void;
	resizeEditingTextarea: () => void;
	buildEditingText: () => string;
	openPinnedEdit: (msg: ChatMessage) => void;
};

export function useMessageListEditing(
	opts: UseMessageListEditingOptions,
): UseMessageListEditingResult {
	const {
		scrollerRef,
		pinOverlayRef,
		messagesRef,
		frameKeysRef,
		stickyCtrl,
		flushStuck,
		requestStuckRef,
		muteStickyLayoutSnap,
		beginStickyEdit,
		endStickyEdit,
		setStickyEditingId,
		scheduleTopFade,
		editingViewportLockRef,
		stickToBottom,
		scrollScheduled,
		hasRows,
		anyStreaming,
		messages,
		streamingText,
		isLoading,
		reasoningText,
		roundSignature,
		agentTasksPinKey,
		activeId,
	} = opts;

	const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
	const [editFlowHeight, setEditFlowHeight] = useState(PROMPT_CHIP_MAX_PX);
	const editFlowHeightRef = useRef(PROMPT_CHIP_MAX_PX);
	editFlowHeightRef.current = editFlowHeight;
	const [editClosing, setEditClosing] = useState(false);
	const editClosingRef = useRef(false);
	const [editingText, setEditingText] = useState('');
	const [editingCaret, setEditingCaret] = useState<number | null>(null);
	const [editingSubmitting, setEditingSubmitting] = useState(false);
	const [editingUploading, setEditingUploading] = useState(false);
	const [editingExistingMediaRefs, setEditingExistingMediaRefs] = useState<string[]>([]);
	const editingExistingMediaRefsRef = useRef<string[]>([]);
	editingExistingMediaRefsRef.current = editingExistingMediaRefs;
	const [editingAttachments, setEditingAttachments] = useState<DraftAttachment[]>([]);
	const editingAttachmentsRef = useRef<DraftAttachment[]>([]);
	editingAttachmentsRef.current = editingAttachments;
	const [modelOpen, setModelOpen] = useState(false);
	const modelMenuId = useId();
	const editRootRef = useRef<HTMLDivElement | null>(null);
	const promptEditRef = useRef<HTMLDivElement | null>(null);
	const editingFilePickerOpenRef = useRef(false);
	const editingScrollTopRef = useRef<number | null>(null);
	const editingScrollPinUntilRef = useRef(0);
	const stickyEditFlowLockRef = useRef(false);
	/** 本次编辑是否走 portal（吸顶浮层）；就地编辑（关闭吸顶）为 false。 */
	const usedPortalRef = useRef(false);
	const prevEditingMessageIdRef = useRef<string | null>(null);

	const editingMessageIdRef = useRef<string | null>(null);
	const openPinnedEditRef = useRef<(msg: ChatMessage) => void>(() => {});

	const editingOverflowAnchorRef = useRef<{
		value: string;
		priority: string;
	} | null>(null);
	const editingFollowTailRef = useRef<boolean | null>(null);
	const editingFollowTailRestoreRef = useRef<{
		value: boolean;
		timer: number | null;
		cleanup: (() => void) | null;
	} | null>(null);
	const editingTextareaRef = useRef<HTMLTextAreaElement | null>(null);
	const editingFileInputRef = useRef<HTMLInputElement | null>(null);
	const editModelMenuRef = useRef<HTMLDivElement | null>(null);

	const {activeSessionId} = useMessageListRollbackStore();

	const syncEditFlowHeightFromVisible = useCallback(() => {
		/* 占位跟可视编辑气泡：底栏展开时 transcript 被顶开，避免取消时高度塌陷抖动 */
		const h = stickyCtrl.measureVisibleEditHeight();
		if (h !== null && stickyCtrl.setEditPlaceholderHeight(h)) {
			setEditFlowHeight(h);
			editFlowHeightRef.current = h;
		}
		requestStuckRef.current();
	}, [stickyCtrl]);

	useLayoutEffect(() => {
		if (!editingMessageId) {
			if (prevEditingMessageIdRef.current !== null) {
				const wasPortal = usedPortalRef.current;
				prevEditingMessageIdRef.current = null;
				editingMessageIdRef.current = null;
				stickyEditFlowLockRef.current = false;
				usedPortalRef.current = false;
				editClosingRef.current = false;
				setEditClosing(false);
				setEditFlowHeight(PROMPT_CHIP_MAX_PX);
				editFlowHeightRef.current = PROMPT_CHIP_MAX_PX;
				setStickyEditingId(null);
				const scroller = scrollerRef.current;
				const pinScroll = editingScrollTopRef.current;
				muteStickyLayoutSnap();
				endStickyEdit();
				/* portal 编辑把 chip 钉在编辑前位置，退出时恢复该滚动点；
				   就地编辑随 transcript 自然滚动，退出保持当前视口不动。 */
				if (wasPortal && scroller && pinScroll !== null) {
					scroller.scrollTop = pinScroll;
					editingScrollPinUntilRef.current = performance.now() + 800;
				}
				/* 同步 flushStuck 而非 schedule:rAF:本提交帧在 useLayoutEffect 内
				   已经移走 portal host,需要 controller 立即 collect+apply 把流内
				   chip 的 visibility:hidden 解除;schedule 会等下一帧,期间用户看到
				   流内 chip 不可见 + 没有 pin——"消失几秒才出现"。 */
				flushStuck();
				if (wasPortal && scroller && pinScroll !== null) {
					scroller.scrollTop = pinScroll;
				}
				const release = window.setTimeout(() => {
					if (editingMessageIdRef.current === null) {
						editingScrollTopRef.current = null;
						editingScrollPinUntilRef.current = 0;
					}
				}, 600);
				return () => window.clearTimeout(release);
			}
			return;
		}
		const portal = usedPortalRef.current;
		prevEditingMessageIdRef.current = editingMessageId;
		editingMessageIdRef.current = editingMessageId;
		setStickyEditingId(editingMessageId);
		const scroller = scrollerRef.current;
		if (portal) {
			const pinScroll =
				editingScrollTopRef.current ?? scroller?.scrollTop ?? null;
			if (scroller && pinScroll !== null) {
				editingScrollTopRef.current = pinScroll;
				scroller.scrollTop = pinScroll;
				/* 编辑全程钉住 scrollTop，避免底栏展开/RO 触发跳动 */
				editingScrollPinUntilRef.current = Number.POSITIVE_INFINITY;
			}
		} else {
			/* 就地编辑（关闭吸顶）：不钉死滚动，允许用户自由滚动看上下文。
			   编辑框长高超出视口底部时由下方 RO 做底部跟随。 */
			editingScrollPinUntilRef.current = 0;
		}
		muteStickyLayoutSnap();
		flushStuck();
		if (portal && scroller) {
			const pinScroll = editingScrollTopRef.current;
			if (pinScroll !== null) {
				scroller.scrollTop = pinScroll;
			}
		}
		scheduleTopFade();
		const editEl = promptEditRef.current;
		const portalHost = stickyCtrl.getEditPortalHost();
		if (typeof ResizeObserver === 'undefined') {
			return;
		}
		/* portal 编辑：把 scrollTop 钉回进入点（防 RO/底栏展开跳动）。
		   就地编辑：编辑框长高超出视口底部 → 滚动跟随（底部始终可见）。 */
		const pinScrollIfNeeded = () => {
			const top = editingScrollTopRef.current;
			if (
				top === null ||
				!scrollerRef.current ||
				performance.now() > editingScrollPinUntilRef.current
			) {
				return;
			}
			scrollerRef.current.scrollTop = top;
		};
		const followInplaceEditBottom = () => {
			const sc = scrollerRef.current;
			const el = editEl ?? promptEditRef.current;
			if (!sc || !el) {
				return;
			}
			const sRect = sc.getBoundingClientRect();
			const eRect = el.getBoundingClientRect();
			const overflow = eRect.bottom - sRect.bottom;
			if (overflow > 0) {
				sc.scrollTop += overflow;
			}
		};
		const ro = new ResizeObserver(() => {
			/* 开/关编辑都跟可视高度，取消收拢时占位同步塌下才不抖 */
			syncEditFlowHeightFromVisible();
			if (portal) {
				pinScrollIfNeeded();
			} else {
				followInplaceEditBottom();
			}
		});
		if (editEl) {
			ro.observe(editEl);
		}
		if (portalHost && portalHost !== editEl) {
			ro.observe(portalHost);
		}
		syncEditFlowHeightFromVisible();
		return () => {
			ro.disconnect();
		};
	}, [
		editingMessageId,
		flushStuck,
		scheduleTopFade,
		muteStickyLayoutSnap,
		setStickyEditingId,
		endStickyEdit,
		stickyCtrl,
		syncEditFlowHeightFromVisible,
	]);

	// React 重绘会覆盖 sticky 内层 className；流式/消息更新后须在本帧绘制前重算 pin。
	useLayoutEffect(() => {
		if (!hasRows) {
			return;
		}
		const pinWindow =
			editingMessageId &&
			performance.now() <= editingScrollPinUntilRef.current;
		const pin = editingScrollTopRef.current;
		const scroller = scrollerRef.current;
		flushStuck();
		if (pinWindow && scroller && pin !== null) {
			scroller.scrollTop = pin;
		}
	}, [
		hasRows,
		flushStuck,
		messages,
		streamingText,
		isLoading,
		reasoningText,
		roundSignature,
		agentTasksPinKey,
		editingMessageId,
	]);

	const cancelDeferredEditingFollowTailRestore = useCallback(() => {
		const pending = editingFollowTailRestoreRef.current;
		if (!pending) {
			return;
		}
		pending.cleanup?.();
		pending.cleanup = null;
		editingFollowTailRestoreRef.current = null;
	}, []);

	const disableEditingScrollAnchor = useCallback(() => {
		const scroller = scrollerRef.current;
		if (!scroller || editingOverflowAnchorRef.current) {
			return;
		}
		editingOverflowAnchorRef.current = {
			value: scroller.style.getPropertyValue('overflow-anchor'),
			priority: scroller.style.getPropertyPriority('overflow-anchor'),
		};
		scroller.style.setProperty('overflow-anchor', 'none');
	}, []);

	const restoreEditingScrollAnchor = useCallback(() => {
		const previous = editingOverflowAnchorRef.current;
		if (!previous) {
			return;
		}
		editingOverflowAnchorRef.current = null;
		const scroller = scrollerRef.current;
		if (!scroller) {
			return;
		}
		if (previous.value) {
			scroller.style.setProperty('overflow-anchor', previous.value, previous.priority);
		} else {
			scroller.style.removeProperty('overflow-anchor');
		}
	}, []);

	const deferEditingFollowTailRestore = useCallback(() => {
		cancelDeferredEditingFollowTailRestore();
		const value = editingFollowTailRef.current;
		editingFollowTailRef.current = null;
		if (value === null) {
			return;
		}
		if (typeof window === 'undefined') {
			stickToBottom.current = value;
			restoreEditingScrollAnchor();
			editingViewportLockRef.current = false;
			return;
		}

		const controls = promptEditRef.current?.querySelector<HTMLElement>(
			'.xy-editing-controls.is-open',
		);
		const pending: {
			value: boolean;
			timer: number | null;
			cleanup: (() => void) | null;
		} = {value, timer: null, cleanup: null};
		const finish = () => {
			if (editingFollowTailRestoreRef.current !== pending) {
				return;
			}
			pending.cleanup?.();
			pending.cleanup = null;
			editingFollowTailRestoreRef.current = null;
			stickToBottom.current = value;
			restoreEditingScrollAnchor();
			editingViewportLockRef.current = false;
		};
		let transitionMs = 0;
		if (controls) {
			const durations = window
				.getComputedStyle(controls)
				.transitionDuration.split(',')
				.map(part => Number.parseFloat(part) * 1000)
				.filter(Number.isFinite);
			transitionMs = Math.max(0, ...durations);
			const onTransitionEnd = (event: TransitionEvent) => {
				if (event.target === controls && event.propertyName === 'grid-template-rows') {
					finish();
				}
			};
			controls.addEventListener('transitionend', onTransitionEnd);
			pending.cleanup = () => {
				controls.removeEventListener('transitionend', onTransitionEnd);
				if (pending.timer !== null) {
					window.clearTimeout(pending.timer);
					window.cancelAnimationFrame(pending.timer);
				}
			};
		}
		editingFollowTailRestoreRef.current = pending;
		if (transitionMs > 0) {
			pending.timer = window.setTimeout(finish, transitionMs + 48);
		} else {
			pending.timer = window.requestAnimationFrame(finish);
		}
	}, [cancelDeferredEditingFollowTailRestore, restoreEditingScrollAnchor]);

	useEffect(() => {
		deferEditingFollowTailRestore();
		for (const attachment of editingAttachmentsRef.current) {
			if (attachment.kind === 'image') URL.revokeObjectURL(attachment.previewUrl);
		}
		editingAttachmentsRef.current = [];
		setEditingAttachments([]);
		setEditingExistingMediaRefs([]);
		editingMessageIdRef.current = null;
		editClosingRef.current = false;
		setEditClosing(false);
		setEditingMessageId(null);
		setEditingText('');
		setEditingCaret(null);
		setModelOpen(false);
	}, [activeId, deferEditingFollowTailRestore]);

	const clearEditingAttachments = useCallback(() => {
		for (const attachment of editingAttachmentsRef.current) {
			if (attachment.kind === 'image') {
				URL.revokeObjectURL(attachment.previewUrl);
			}
		}
		editingAttachmentsRef.current = [];
		setEditingAttachments([]);
		setEditingExistingMediaRefs([]);
	}, []);

	const beginEdit = useCallback(
		(
			message: Pick<ChatMessage, 'id' | 'text' | 'mediaRefs'>,
			event?: MouseEvent<HTMLDivElement>,
		) => {
			let caret: number | null = null;

			cancelDeferredEditingFollowTailRestore();
			if (event) {
				const textNode =
					event.currentTarget.querySelector<HTMLElement>('.xy-chat-text');
				const dom = document as Document & {
					caretRangeFromPoint?: (x: number, y: number) => Range | null;
					caretPositionFromPoint?: (
						x: number,
						y: number,
					) => {offsetNode: Node; offset: number} | null;
				};
				const range = dom.caretRangeFromPoint?.(event.clientX, event.clientY);
				const position = dom.caretPositionFromPoint?.(
					event.clientX,
					event.clientY,
				);
				const container = range?.startContainer ?? position?.offsetNode;
				const offset = range?.startOffset ?? position?.offset;
				if (
					textNode &&
					container &&
					offset !== undefined &&
					textNode.contains(container)
				) {
					const before = document.createRange();
					before.selectNodeContents(textNode);
					before.setEnd(container, offset);
					caret = before.toString().length;
				}
			}
			setModelOpen(false);
			if (editingFollowTailRef.current === null) {
				editingFollowTailRef.current = stickToBottom.current;
			}
			disableEditingScrollAnchor();
			editingViewportLockRef.current = true;
			cancelFrameTask(frameKeysRef.current!.scroll);
			scrollScheduled.current = false;
			stickToBottom.current = false;
			const scroller = scrollerRef.current;
			const savedScrollTop = scroller?.scrollTop ?? null;
			if (savedScrollTop !== null) {
				editingScrollTopRef.current = savedScrollTop;
				editingScrollPinUntilRef.current = performance.now() + 800;
			}
			clearEditingAttachments();
			setEditingExistingMediaRefs(message.mediaRefs?.slice() ?? []);
			editingMessageIdRef.current = message.id;
			const editResult = beginStickyEdit({
				id: message.id,
				text: message.text,
			});
			stickyEditFlowLockRef.current = editResult.usedPortal;
			usedPortalRef.current = editResult.usedPortal;
			if (editResult.scrollTop !== null && scroller) {
				scroller.scrollTop = editResult.scrollTop;
			}
			flushSync(() => {
				setEditClosing(false);
				editClosingRef.current = false;
				setEditFlowHeight(editResult.placeholderHeight);
				editFlowHeightRef.current = editResult.placeholderHeight;
				setEditingMessageId(message.id);
				setEditingText(message.text);
				setEditingCaret(caret);
			});
			if (scroller && savedScrollTop !== null && editResult.usedPortal) {
				/* 仅 portal 编辑需要硬钉：chip 已浮到吸顶层，流内原位塌空，
				   必须把 scrollTop 钉在编辑前位置才不跳。就地编辑(chip 留在
				   流内原位展开)随 transcript 自然滚动，此处不再设 Infinity 钉
				   ——入口 layout effect 已把 pin window 清零，放行用户滚动。 */
				const pin = savedScrollTop;
				editingScrollTopRef.current = pin;
				editingScrollPinUntilRef.current = Number.POSITIVE_INFINITY;
				scroller.scrollTop = pin;
				queueMicrotask(() => {
					if (scrollerRef.current === scroller) {
						scroller.scrollTop = pin;
					}
				});
				requestAnimationFrame(() => {
					if (scrollerRef.current === scroller) {
						scroller.scrollTop = pin;
					}
				});
			}
		},
		[
			beginStickyEdit,
			clearEditingAttachments,
			disableEditingScrollAnchor,
		],
	);

	const toggleModel = useCallback(() => {
		if (editingSubmitting || anyStreaming) {
			return;
		}
		setModelOpen(value => !value);
	}, [anyStreaming, editingSubmitting]);
	const closeModel = useCallback(() => setModelOpen(false), []);

	const resizeEditingTextarea = useCallback(() => {
		const node = editingTextareaRef.current;
		if (!node) {
			return;
		}
		/* 自动撑高：textarea 的 height:auto 恒等于 rows(1) 一行，长消息会塌成 ~50px，
		   必须按 scrollHeight 设真实内容高。上限由父 .xy-editing-bubble 的
		   max-height: var(--xy-prompt-view-cap) 封顶；超出部分由 flex-shrink + 内部滚动。 */
		node.style.height = 'auto';
		node.style.height = `${node.scrollHeight}px`;
		node.style.overflowY = 'auto';
	}, []);

	const onEditAttachmentPick = useCallback(
		async (fileList: FileList | File[] | null) => {
			if (!fileList || editingSubmitting || anyStreaming) {
				return;
			}
			const files = Array.from(fileList);
			const images = files.filter(file => file.type.startsWith('image/'));
			const otherFiles = files.filter(file => !file.type.startsWith('image/'));
			const acceptedImages: DraftAttachment[] = [];
			for (const file of images) {
				if (file.size > 8 * 1024 * 1024) {
					toast.info(`图片 ${file.name} 超过 8MB`);
					continue;
				}
				acceptedImages.push({
					kind: 'image',
					id: uid('edit-img'),
					name: file.name || 'image.png',
					previewUrl: URL.createObjectURL(file),
					mime: file.type || 'image/png',
					bytes: file.size,
					file,
				});
			}
			if (acceptedImages.length > 0) {
				setEditingAttachments(previous => {
					const imageCount = previous.filter(item => item.kind === 'image').length;
					const room = Math.max(0, 8 - editingExistingMediaRefs.length - imageCount);
					const accepted = acceptedImages.slice(0, room);
					for (const dropped of acceptedImages.slice(room)) {
						if (dropped.kind === 'image') URL.revokeObjectURL(dropped.previewUrl);
					}
					if (accepted.length < acceptedImages.length && room === 0) {
						toast.info('最多添加 8 张图片');
					}
					return [...previous, ...accepted];
				});
			}
			if (otherFiles.length === 0) {
				return;
			}
			setEditingUploading(true);
			try {
				for (const file of otherFiles) {
					const uploaded = await uploadFile(file);
					setEditingAttachments(previous => [
						...previous,
						{
							kind: 'file',
							id: uid('edit-file'),
							name: uploaded.filename || file.name,
							text: uploaded.text,
						},
					]);
				}
			} catch (error) {
				toast.error(error instanceof Error ? error.message : String(error));
			} finally {
				setEditingUploading(false);
			}
		},
		[anyStreaming, editingExistingMediaRefs.length, editingSubmitting],
	);

	const onRemoveEditAttachment = useCallback((id: string) => {
		setEditingAttachments(previous => {
			const removed = previous.find(item => item.id === id);
			if (removed?.kind === 'image') URL.revokeObjectURL(removed.previewUrl);
			return previous.filter(item => item.id !== id);
		});
	}, []);

	const buildEditingText = useCallback(() => {
		const parts = [editingText.trim()];
		for (const attachment of editingAttachmentsRef.current) {
			if (attachment.kind === 'file') {
				if (attachment.path && !attachment.text) {
					parts.push(`\n\n@${attachment.path.replace(/\\/g, '/')}`);
				} else if (attachment.text) {
					parts.push(
						`\n\n[附件: ${attachment.name}]\n\`\`\`\n${attachment.text}\n\`\`\`\n`,
					);
				} else if (attachment.path) {
					parts.push(`\n\n@${attachment.path.replace(/\\/g, '/')}`);
				}
			}
		}
		return parts.join('').trim() || (editingExistingMediaRefsRef.current.length || editingAttachmentsRef.current.some(item => item.kind === 'image') ? '请分析这些图片。' : '');
	}, [editingText]);

	useLayoutEffect(() => {
		const node = editingTextareaRef.current;
		if (!editingMessageId || !node) {
			return;
		}
		node.focus({preventScroll: true});
		const caret = Math.min(
			node.value.length,
			Math.max(0, editingCaret ?? node.value.length),
		);
		node.setSelectionRange(caret, caret);
		resizeEditingTextarea();
	}, [editingCaret, editingMessageId, resizeEditingTextarea]);

	const cancelEdit = useCallback(() => {
		if (editingSubmitting || editClosingRef.current) {
			return;
		}
		editingFilePickerOpenRef.current = false;
		const scroller = scrollerRef.current;
		const pinScroll =
			editingScrollTopRef.current ?? scroller?.scrollTop ?? null;
		if (scroller && pinScroll !== null) {
			editingScrollTopRef.current = pinScroll;
			editingScrollPinUntilRef.current = performance.now() + 900;
			/* chip 切到编辑态那一瞬,chrome 会把 scroller.scrollTop 静默改写到
			   另一个位置(实测 savedScrollTop=58 → 29)。退出时如果直接
			   scroller.scrollTop = pinScroll,等于在 grid-template-rows 1fr→0fr
			   220ms 收缩动画中间硬跳上方内容 29px = 用户看到的"闪"。改用 scrollTo
			   smooth 让 scrollTop 与 chip 高度同步平滑过渡回 savedScrollTop。*/
			if (Math.abs((scroller.scrollTop ?? 0) - pinScroll) > 0.5) {
				try {
					scroller.scrollTo({top: pinScroll, behavior: 'smooth'});
				} catch {
					scroller.scrollTop = pinScroll;
				}
			} else {
				scroller.scrollTop = pinScroll;
			}
		}
		muteStickyLayoutSnap();
		/* 先收控件，等高度塌完再拆编辑态，避免界面一抖 */
		editClosingRef.current = true;
		setEditClosing(true);
		const finish = () => {
			if (!editClosingRef.current) {
				return;
			}
			/* 拆编辑前最后把占位钉到气泡当前可视高:收拢动画期间占位高度靠
			   RO 逐帧跟随(回调在布局后触发、天然滞后帧边界),若切换 commit
			   前最后一拍漏跟,占位会停在偏高的旧值,占位换真 chip 的瞬间
			   高度差一次性释放 = 内容硬跳一截。此处同步测量并直写占位 inline
			   (不经 React,无渲染滞后),使拆编辑时刻占位高与真 chip 高一致。 */
			const settleH = stickyCtrl.measureVisibleEditHeight();
			if (settleH !== null) {
				stickyCtrl.setEditPlaceholderHeight(settleH);
			}
			deferEditingFollowTailRestore();
			if (scroller && pinScroll !== null) {
				scroller.scrollTop = pinScroll;
			}
			editingMessageIdRef.current = null;
			clearEditingAttachments();
			setEditingMessageId(null);
			setEditingText('');
			setEditingCaret(null);
			setModelOpen(false);
			editClosingRef.current = false;
			setEditClosing(false);
			/* 同步跑一次 flushStuck(不走 scheduleFrameRead):
			   endStickyEdit() 同步把 portal host 子树从 overlay 移除 → 编辑气泡
			   立刻在屏幕上消失 → 流内 chip 的 visibility:hidden 还在
			   (上一次 flush 留下的 stuck state)→ 顶部 pin 也已不在 → 用户看到
			   的就是 chip 消失若干帧才回来。flushStuck 用同一栈同步触发
			   collect()+apply(),让 controller 立即按当前 chip 真实 rect 重新评估
			   stuck,设回 visibility:visible。请求下一帧已晚——此处要的是"零等待"，
			   否则用户感觉"消失几秒才出现"。 */
			flushStuck();
		};
		/* 等编辑气泡 max-height 从 121 渐缩回 96（200ms）再拆编辑器 → 退出不瞬移。
		   以气泡自身为监听源（覆盖吸顶 portal 与流内）。 */
		const bubble = promptEditRef.current;
		let settled = false;
		const settle = () => {
			if (settled) {
				return;
			}
			settled = true;
			finish();
		};
		if (bubble) {
			const onEnd = (event: TransitionEvent) => {
				if (
					event.target === bubble &&
					event.propertyName === 'max-height'
				) {
					bubble.removeEventListener('transitionend', onEnd);
					settle();
				}
			};
			bubble.addEventListener('transitionend', onEnd);
			/* 守卫超时兜底（覆盖 max-height 过渡 200ms + 控件收起），避免卡顿 */
			window.setTimeout(settle, 260);
		} else {
			settle();
		}
	}, [
		clearEditingAttachments,
		deferEditingFollowTailRestore,
		editingSubmitting,
		flushStuck,
		muteStickyLayoutSnap,
	]);

	useEffect(() => {
		if (!editingMessageId) {
			return;
		}
		const onPointerDown = (event: PointerEvent) => {
			const target = event.target;
			if (!(target instanceof Node)) {
				return;
			}
			if (editingFilePickerOpenRef.current) {
				return;
			}
			if (target instanceof Element && target.closest('[data-xy-file-picker]')) {
				return;
			}
			const portalMenu = modelOpen
				? document.getElementById(modelMenuId)
				: null;
			const insidePortalMenu = Boolean(portalMenu?.contains(target));
			if (
				modelOpen &&
				!editModelMenuRef.current?.contains(target) &&
				!insidePortalMenu
			) {
				setModelOpen(false);
			}
			if (
				!editRootRef.current?.contains(target) &&
				!promptEditRef.current?.contains(target) &&
				!insidePortalMenu
			) {
				cancelEdit();
			}
		};

		document.addEventListener('pointerdown', onPointerDown);
		return () => document.removeEventListener('pointerdown', onPointerDown);
	}, [cancelEdit, editingMessageId, modelMenuId, modelOpen]);

	useEffect(() => {
		if (!editingMessageId) {
			return;
		}
		const releaseFilePickerGuard = () => {
			editingFilePickerOpenRef.current = false;
		};
		window.addEventListener('focus', releaseFilePickerGuard);
		return () => window.removeEventListener('focus', releaseFilePickerGuard);
	}, [editingMessageId]);

	const submitEdit = useCallback(async () => {
		if (!editingMessageId || !buildEditingText() || editingSubmitting || editingUploading || !activeSessionId) {
			return;
		}
		setEditingSubmitting(true);
		try {
			/* 回溯 v3 热路径：编辑提交直接打开弹窗（跳过 preview，合同 31） */
			const text = buildEditingText();
			useRewindV3Store.getState().openDialog(activeSessionId, editingMessageId, text);
			deferEditingFollowTailRestore();
			clearEditingAttachments();
			editingMessageIdRef.current = null;
			setEditingMessageId(null);
			setEditingText('');
			setEditingCaret(null);
			setModelOpen(false);
		} finally {
			setEditingSubmitting(false);
		}
	}, [
		activeSessionId,
		buildEditingText,
		clearEditingAttachments,
		deferEditingFollowTailRestore,
		editingMessageId,
		editingSubmitting,
		editingUploading,
	]);

	const openPinnedEdit = (msg: ChatMessage) => {
		beginEdit(msg);
	};
	openPinnedEditRef.current = openPinnedEdit;

	useLayoutEffect(() => {
		if (!hasRows) {
			return;
		}
		const overlay = pinOverlayRef.current;
		if (!overlay) {
			return;
		}
		const onPinClick = (event: globalThis.MouseEvent) => {
			const wrap = (event.target as HTMLElement).closest<HTMLElement>(
				'[data-pin-id]',
			);
			const id = wrap?.dataset.pinId;
			/* 仅当确实正处该 id 的编辑态才拦截；否则即便 ref 残留（上次编辑未干净复位）
			   也放行再次进入，修掉「第二次点不进编辑」。 */
			const editingNow =
				editingMessageIdRef.current === id &&
				stickyCtrl.getPhase().kind === 'editing';
			if (!id || editingNow) {
				return;
			}
			if (!stickyCtrl.isPinEditable(id)) {
				return;
			}
			const msg = messagesRef.current.find(m => m.id === id);
			if (msg) {
				openPinnedEditRef.current(msg);
			}
		};
		const onPinKeyDown = (event: globalThis.KeyboardEvent) => {
			if (event.key !== 'Enter' && event.key !== ' ') {
				return;
			}
			const wrap = (event.target as HTMLElement).closest<HTMLElement>(
				'[data-pin-id]',
			);
			const id = wrap?.dataset.pinId;
			const editingNow =
				editingMessageIdRef.current === id &&
				stickyCtrl.getPhase().kind === 'editing';
			if (!id || editingNow) {
				return;
			}
			if (!stickyCtrl.isPinEditable(id)) {
				return;
			}
			event.preventDefault();
			const msg = messagesRef.current.find(m => m.id === id);
			if (msg) {
				openPinnedEditRef.current(msg);
			}
		};
		overlay.addEventListener('click', onPinClick);
		overlay.addEventListener('keydown', onPinKeyDown);
		return () => {
			overlay.removeEventListener('click', onPinClick);
			overlay.removeEventListener('keydown', onPinKeyDown);
		};
	}, [hasRows]);

	return {
		editingMessageId,
		editingText,
		setEditingText,
		editingCaret,
		editingSubmitting,
		editingUploading,
		editingAttachments,
		editingExistingMediaRefs,
		editFlowHeight,
		editClosing,
		modelOpen,
		modelMenuId,
		editRootRef,
		promptEditRef,
		editingTextareaRef,
		editingFilePickerOpenRef,
		editingFileInputRef,
		editModelMenuRef,
		stickyEditFlowLockRef,
		beginEdit,
		cancelEdit,
		submitEdit,
		toggleModel,
		closeModel,
		onEditAttachmentPick,
		onRemoveEditAttachment,
		resizeEditingTextarea,
		buildEditingText,
		openPinnedEdit,
	};
}
