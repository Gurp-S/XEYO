/**
 * Viewport / scroll cluster extracted from messageList/MessageList.tsx.
 * Behavior unchanged: virtual-scroll follow-tail, rAF sticky/pin flush,
 * session-switch landing, rail active tracking.
 */
import {
	useCallback,
	useLayoutEffect,
	useRef,
	useState,
	type Dispatch,
	type RefObject,
	type SetStateAction,
} from 'react';
import {
	cancelFrameTask,
	scheduleFrameRead,
	scheduleFrameWrite,
} from '@/lib/frameScheduler';
import {
	gapFromBottom,
	isUserScrollingFresh,
	nextFollowTailPinned,
	noteUserScrollGesture,
	writeFollowTail,
} from '@/lib/chatScroll';
import type {ChatMessage} from '@/lib/types';
import type {VirtualRoundListApi} from '../VirtualRoundList';
import type {TurnRailItem} from '../TurnRail';
import type {StickyPromptController} from '../sticky/StickyPromptController';

type FrameKeys = {
	scroll: string;
	topFade: string;
	rail: string;
	stuck: string;
};

export type UseMessageListViewportOptions = {
	scrollerRef: RefObject<HTMLDivElement | null>;
	contentRef: RefObject<HTMLDivElement | null>;
	pinOverlayRef: RefObject<HTMLDivElement | null>;
	frameKeysRef: RefObject<FrameKeys | null>;
	stickyCtrl: StickyPromptController;
	flushStuck: () => void;
	requestStuck: () => void;
	requestStuckRef: RefObject<() => void>;
	stickyLayoutMuteRef: RefObject<boolean>;
	/** Shared with the editing cluster: edit-lock read by follow-tail scroll. */
	editingViewportLockRef: RefObject<boolean>;
	stickToBottom: RefObject<boolean>;
	scrollScheduled: RefObject<boolean>;
	railItemsRef: RefObject<TurnRailItem[]>;
	/** 全部轮次 id（rail 高亮 / 跳轮的前缀和映射用）。 */
	roundIdsRef: RefObject<readonly string[]>;
	/** VirtualRoundList 前缀和句柄（窗口化时非 null）。 */
	windowApiRef: RefObject<VirtualRoundListApi | null>;
	roundSignature: string;
	setForceMount: Dispatch<SetStateAction<Record<string, true>>>;
	hasRows: boolean;
	streaming: boolean;
	agentTasksPinKey: string;
	activeId: string | null;
	messages: ChatMessage[];
	scheduleTopFade: () => void;
	syncTopFade: () => void;
	hover: {
		scrollerRef: (el: HTMLElement | null) => void;
	};
};

export type UseMessageListViewportResult = {
	scrollerEl: HTMLDivElement | null;
	setScrollerNode: (node: HTMLDivElement | null) => void;
	jumpToRound: (roundId: string) => void;
	sessionSwitching: boolean;
	railActiveId: string | null;
};

export function useMessageListViewport(
	opts: UseMessageListViewportOptions,
): UseMessageListViewportResult {
	const {
		scrollerRef,
		contentRef,
		pinOverlayRef,
		frameKeysRef,
		stickyCtrl,
		flushStuck,
		requestStuck,
		requestStuckRef,
		stickyLayoutMuteRef,
		editingViewportLockRef,
		stickToBottom,
		scrollScheduled,
		railItemsRef,
		roundIdsRef,
		windowApiRef,
		roundSignature,
		setForceMount,
		hasRows,
		streaming,
		agentTasksPinKey,
		activeId,
		messages,
		scheduleTopFade,
		syncTopFade,
		hover,
	} = opts;

	const [scrollerEl, setScrollerEl] = useState<HTMLDivElement | null>(null);
	const prevMsgLen = useRef(0);
	const roundNodesRef = useRef<HTMLElement[]>([]);
	const [railActiveId, setRailActiveId] = useState<string | null>(null);
	/** rail 条目 id 集合（仅当 railItemsRef 引用变化时重建，避免每帧 O(n)）。 */
	const railSetRef = useRef<{src: TurnRailItem[]; ids: Set<string>} | null>(
		null,
	);
	const railIdSet = useCallback(() => {
		const items = railItemsRef.current;
		if (!railSetRef.current || railSetRef.current.src !== items) {
			railSetRef.current = {
				src: items,
				ids: new Set(items.map(item => item.id)),
			};
		}
		return railSetRef.current.ids;
	}, [railItemsRef]);

	useLayoutEffect(() => {
		const scroller = scrollerRef.current;
		if (!scroller) {
			roundNodesRef.current = [];
			return;
		}
		roundNodesRef.current = Array.from(
			scroller.querySelectorAll<HTMLElement>('[data-round-id]'),
		);
	}, [roundSignature, scrollerEl]);

	const syncRailActive = useCallback(() => {
		const scroller = scrollerRef.current;
		const items = railItemsRef.current;
		if (!scroller || items.length === 0) {
			return;
		}
		const gap =
			scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
		if (gap < 80) {
			const last = items[items.length - 1]?.id ?? null;
			setRailActiveId(prev => (prev === last ? prev : last));
			return;
		}
		const readOffset = Math.min(96, scroller.clientHeight * 0.28);
		let current: string | null = items[0]?.id ?? null;
		const ids = roundIdsRef.current;
		const api = windowApiRef.current;
		if (api && ids.length > 0) {
			// 窗口化：DOM 只剩挂载段，offsetTop 二分不可用。改用 VirtualRoundList
			// 的前缀和（spacer 布局 = Σ 缓存高度，与真实 DOM 偏移一致）。
			const idx = Math.min(
				api.indexAt(scroller.scrollTop + readOffset),
				ids.length - 1,
			);
			// 命中无用户消息的孤儿轮时回退到最近的用户轮（rail 条目只含用户轮）。
			const railIds = railIdSet();
			for (let i = idx; i >= 0; i -= 1) {
				const id = ids[i];
				if (id && railIds.has(id)) {
					current = id;
					break;
				}
			}
		} else {
			// 兜底：api 未就绪（首个滚动事件先于列表布局 effect）时用 DOM 二分。
			// RoundMount sections are direct children of the transcript content.
			// Their offsetTop is equivalent to rect.top - scroller rect.top +
			// scrollTop, without a per-frame getBoundingClientRect layout read.
			const elements = roundNodesRef.current;
			let low = 0;
			let high = elements.length - 1;
			while (low <= high) {
				const mid = (low + high) >> 1;
				const el = elements[mid];
				if (!el) {
					break;
				}
				if (el.offsetTop - scroller.scrollTop <= readOffset) {
					current = el.dataset.roundId || current;
					low = mid + 1;
				} else {
					high = mid - 1;
				}
			}
		}
		setRailActiveId(prev => (prev === current ? prev : current));
	}, [scrollerRef, railItemsRef, roundIdsRef, windowApiRef, railIdSet]);

	const setScrollerNode = useCallback(
		(node: HTMLDivElement | null) => {
			if (scrollerRef.current === node) {
				return;
			}
			scrollerRef.current = node;
			setScrollerEl(node);
			hover.scrollerRef(node);
			if (node) {
				scheduleTopFade();
				requestStuckRef.current();
			}
		},
		[hover.scrollerRef, scheduleTopFade, scrollerRef, requestStuckRef],
	);

	/* ---- 会话切换滚动位置记忆（smoke-test #14）----
	   - saved: {top, pinned} 按 sessionId 保存;当前会话滚动/切走时写回。
	   - 切换时: 有记忆 → 恢复 top+pinned;无记忆 → 视为新会话,默认贴底。
	   - 冷会话(scroller 未挂载) → landingPending 挂起,消息载入后由
	     messages.length effect 一次性落地(且消费掉本轮增长,避免 snap 覆盖恢复点)。 */
	const activeIdRef = useRef(activeId);
	activeIdRef.current = activeId;
	const scrollMemoryRef = useRef<Map<string, {top: number; pinned: boolean}>>(
		new Map(),
	);
	const landingPendingRef = useRef<{
		sessionId: string | null;
		saved: {top: number; pinned: boolean} | null;
		applied: boolean;
	}>({sessionId: null, saved: null, applied: false});
	const applyLanding = useCallback(
		(scroller: HTMLDivElement, saved: {top: number; pinned: boolean} | null) => {
			if (saved) {
				stickToBottom.current = saved.pinned;
				if (saved.pinned) {
					writeFollowTail(scroller, true);
				} else {
					const maxTop = Math.max(
						0,
						scroller.scrollHeight - scroller.clientHeight,
					);
					scroller.scrollTop = Math.max(0, Math.min(saved.top, maxTop));
				}
				return;
			}
			stickToBottom.current = true;
			writeFollowTail(scroller, true);
		},
		[stickToBottom],
	);

	const jumpToRound = useCallback(
		(roundId: string) => {
			setForceMount(prev =>
				prev[roundId] ? prev : {...prev, [roundId]: true},
			);
			const run = () => {
				const scroller = scrollerRef.current;
				if (!scroller) {
					return;
				}
				const el = scroller.querySelector<HTMLElement>(
					`[data-round-id="${CSS.escape(roundId)}"]`,
				);
				if (el) {
					stickToBottom.current = false;
					const top =
						el.getBoundingClientRect().top -
						scroller.getBoundingClientRect().top +
						scroller.scrollTop -
						8;
					scroller.scrollTo({top: Math.max(0, top), behavior: 'smooth'});
					setRailActiveId(roundId);
					return;
				}
				// 目标在窗口外（窗口化未挂载）：按前缀和先瞬移，让窗口装下目标，
				// 下一帧再用真实 DOM 位置平滑精调。
				const idx = roundIdsRef.current.indexOf(roundId);
				const api = windowApiRef.current;
				if (idx < 0 || !api) {
					return;
				}
				stickToBottom.current = false;
				scroller.scrollTo({top: Math.max(0, api.offsetOf(idx) - 8)});
				setRailActiveId(roundId);
				requestAnimationFrame(() => {
					const scroller2 = scrollerRef.current;
					const el2 = scroller2?.querySelector<HTMLElement>(
						`[data-round-id="${CSS.escape(roundId)}"]`,
					);
					if (!scroller2 || !el2) {
						return;
					}
					const top =
						el2.getBoundingClientRect().top -
						scroller2.getBoundingClientRect().top +
						scroller2.scrollTop -
						8;
					scroller2.scrollTo({top: Math.max(0, top), behavior: 'smooth'});
				});
			};
			requestAnimationFrame(run);
		},
		[setForceMount, scrollerRef, stickToBottom, roundIdsRef, windowApiRef],
	);

	const snapToBottom = () => {
		if (
			editingViewportLockRef.current ||
			scrollScheduled.current ||
			stickyLayoutMuteRef.current
		) {
			return;
		}
		scrollScheduled.current = true;
		scheduleFrameWrite(frameKeysRef.current!.scroll, () => {
			scrollScheduled.current = false;
			if (
				editingViewportLockRef.current ||
				stickyLayoutMuteRef.current
			) {
				return;
			}
			// 用户正在滚动手势中（滚轮/触摸/拖滚动条）：程序化贴底让路，
			// 否则内容 resize 的 snap 与用户滚动互相争抢 = 滚动条乱跳。
			// 手势结束后 scroll 处理器会按贴底滞回重新钉住。
			if (isUserScrollingFresh()) {
				return;
			}
			const scroller = scrollerRef.current;
			if (!scroller) {
				return;
			}
			writeFollowTail(scroller, stickToBottom.current);
		});
	};

	useLayoutEffect(() => {
		const el = scrollerRef.current;
		if (!el || !hasRows) {
			return;
		}
		let lastScrollTop = el.scrollTop;
		const onScroll = () => {
			if (!editingViewportLockRef.current) {
				const gap = gapFromBottom(
					el.scrollHeight,
					el.scrollTop,
					el.clientHeight,
				);
				const scrolledUp = el.scrollTop < lastScrollTop - 0.5;
				stickToBottom.current = nextFollowTailPinned(
					stickToBottom.current,
					gap,
					scrolledUp,
				);
			}
			// 会话滚动位置记忆：当前会话随时更新（切走时以最新值为准）。
			const sid = activeIdRef.current;
			if (sid) {
				scrollMemoryRef.current.set(sid, {
					top: el.scrollTop,
					pinned: stickToBottom.current,
				});
			}
			lastScrollTop = el.scrollTop;
			// 同步更新打孔/pin，避免 compositor 滚动先绘制、rAF 后补偿的一帧透出。
			flushStuck();
			scheduleFrameRead(frameKeysRef.current!.rail, syncRailActive);
			scheduleTopFade();
		};
		el.addEventListener('scroll', onScroll, {passive: true});
		window.addEventListener('resize', onScroll);
		// 用户滚动手势记账：滚轮 / 触摸 / 按住滚动条拖动。
		// 手势窗口内 snapToBottom 让路，消除「贴底 snap vs 用户滚动」互抢。
		const noteGesture = () => noteUserScrollGesture();
		el.addEventListener('wheel', noteGesture, {passive: true});
		el.addEventListener('touchstart', noteGesture, {passive: true});
		el.addEventListener('pointerdown', noteGesture, {passive: true});
		const ro =
			typeof ResizeObserver !== 'undefined'
				? new ResizeObserver(() => {
						scheduleFrameRead(frameKeysRef.current!.rail, syncRailActive);
						scheduleTopFade();
						requestStuck();
					})
				: null;
		ro?.observe(el);
		if (contentRef.current) {
			ro?.observe(contentRef.current);
		}
		scheduleFrameRead(frameKeysRef.current!.rail, syncRailActive);
		scheduleTopFade();
		requestStuck();
		return () => {
			el.removeEventListener('scroll', onScroll);
			window.removeEventListener('resize', onScroll);
			el.removeEventListener('wheel', noteGesture);
			el.removeEventListener('touchstart', noteGesture);
			el.removeEventListener('pointerdown', noteGesture);
			ro?.disconnect();
		};
	}, [hasRows, flushStuck, scheduleTopFade, syncRailActive]);

	useLayoutEffect(() => {
		if (!hasRows) {
			prevMsgLen.current = messages.length;
			return;
		}
		// 冷会话落地（smoke-test #14）：切换时 scroller 尚未挂载,消息载入后在此
		// 一次性恢复滚动点;恢复点接管本帧落点后消费掉本轮增长,避免 snap 覆盖。
		let landedRestore = false;
		const pending = landingPendingRef.current;
		const pendingScroller = scrollerRef.current;
		if (
			pending &&
			pending.sessionId === activeId &&
			!pending.applied &&
			pendingScroller
		) {
			pending.applied = true;
			applyLanding(pendingScroller, pending.saved);
			landedRestore = true;
		}
		const prev = prevMsgLen.current;
		const grew = messages.length > prev;
		prevMsgLen.current = messages.length;
		if (landedRestore) {
			return;
		}
		const last = messages[messages.length - 1];
		if (
			!editingViewportLockRef.current &&
			grew &&
			(prev === 0 || last?.role === 'user')
		) {
			stickToBottom.current = true;
			snapToBottom();
		}
	}, [messages.length, hasRows, messages]);

	useLayoutEffect(() => {
		if (!hasRows) {
			return;
		}
		const content = contentRef.current;
		if (!content || typeof ResizeObserver === 'undefined') {
			return;
		}
		const ro = new ResizeObserver(() => {
			if (
				stickToBottom.current &&
				!editingViewportLockRef.current &&
				!stickyLayoutMuteRef.current
			) {
				snapToBottom();
			}
			requestStuck();
		});
		ro.observe(content);
		requestStuck();
		return () => {
			ro.disconnect();
			cancelFrameTask(frameKeysRef.current!.scroll);
			cancelFrameTask(frameKeysRef.current!.topFade);
			cancelFrameTask(frameKeysRef.current!.rail);
			cancelFrameTask(frameKeysRef.current!.stuck);
			scrollScheduled.current = false;
		};
	}, [hasRows, requestStuck, streaming, agentTasksPinKey]);

	const sessionSwitchRef = useRef(activeId);
	const sessionSwitching = sessionSwitchRef.current !== activeId;
	useLayoutEffect(() => {
		// 0) 落点先行：与 ResizeObserver→snapToBottom 完全同一规则
		//    （writeFollowTail + stickToBottom），但从下一帧提前到本帧绘制前。
		//    否则首帧停留在旧会话的滚动位置（或被 clamp 的位置），下一帧才跳
		//    到底，两幅不同的画面即肉眼可见的闪动；下面的吸顶测量也必须以
		//    落位后的几何为准，否则 Pin 孔位全错。
		//    smoke-test #14：切换前先保存旧会话滚动点;新会话有记忆则恢复,
		//    无记忆默认贴底;冷会话(scroller 未挂载)挂起由 messages 载入时落地。
		const prevId = sessionSwitchRef.current;
		const landingScroller = scrollerRef.current;
		if (
			prevId &&
			prevId !== activeId &&
			landingScroller &&
			hasRows
		) {
			scrollMemoryRef.current.set(prevId, {
				top: landingScroller.scrollTop,
				pinned: stickToBottom.current,
			});
		}
		const saved = activeId
			? (scrollMemoryRef.current.get(activeId) ?? null)
			: null;
		landingPendingRef.current = {
			sessionId: activeId,
			saved,
			applied: Boolean(landingScroller && hasRows),
		};
		if (landingScroller && hasRows) {
			applyLanding(landingScroller, saved);
		}
		sessionSwitchRef.current = activeId;
		stickyCtrl.bindDom({
			scroller: scrollerRef.current,
			content: contentRef.current,
			overlay: pinOverlayRef.current,
		});
		stickyCtrl.resetSession();

		scrollerRef.current?.style.removeProperty('--xy-top-fade-h');
		// 会话切换后、本帧绘制前同步收口，避免旧状态泄露进第一个可见帧
		flushStuck();
		syncTopFade();
		scheduleTopFade();
		requestStuckRef.current();
		/* 子树 ref 可能晚一拍挂上，再补一次吸顶限制 */
		requestAnimationFrame(() => requestStuckRef.current());
	}, [activeId, flushStuck, scheduleTopFade, stickyCtrl, syncTopFade]);

	return {
		scrollerEl,
		setScrollerNode,
		jumpToRound,
		sessionSwitching,
		railActiveId,
	};
}
