/**
 * 消息列表外壳——轮次、吸顶编辑、回溯药丸。
 */
import {
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
} from 'react';

import {useHoverScroll} from '@/hooks/useHoverScroll';
import {
	roundStreamHostProps,
	useMessageListRollbackStore,
	useMessageListStore,
} from '@/hooks/useMessageListStore';

import {RewindCutPill} from '../WorkspaceRevertDialog';
import {useRewindV3Store, type RewindPill} from '@/stores/rewindV3Store';
import {useChatStore} from '@/stores/chatStore';
import {SIDE_SPACE_ID} from '@/lib/db';
import {useSettingsStore} from '@/stores/settingsStore';
import {pickEmptyQuip} from '@/lib/emptyQuips';
import {groupTranscript, patchTranscriptTail, type TranscriptBlock} from '@/lib/groupTranscript';
import {
	createFrameKey,
	scheduleFrameRead,
} from '@/lib/frameScheduler';
import {
	collectLatestTodosFromItems,
} from '@/lib/toolActivity';
import type {ChatMessage} from '@/lib/types';
import {TurnRail, type TurnRailItem} from '../TurnRail';
import {VirtualRoundList, type VirtualRoundListApi} from '../VirtualRoundList';
import {
	EditPortalHostContext,
	acquireSelfWallpaper,
	releaseSelfWallpaper,
	useStickyPromptController,
} from '../sticky';
import {MessageListProps, Round} from './types';
import {roundsWithAgentTasks, groupRounds, reuseRoundPrefix} from './groupRounds';
import {EmptyState} from './EmptyState';
import {RoundHost} from './RoundHost';
import {useMessageListViewport} from './useMessageListViewport';
import {useMessageListEditing} from './useMessageListEditing';
import {RollbackDialogs} from './RollbackDialogs';
import {findRoundPills} from './pills';

type BlockOpts = {
	streamingText?: string;
	isLoading: boolean;
	statusText?: string;
	reasoningText?: string;
};

function blockOptsSame(a: BlockOpts, b: BlockOpts): boolean {
	return (
		a.streamingText === b.streamingText &&
		a.isLoading === b.isLoading &&
		a.statusText === b.statusText &&
		a.reasoningText === b.reasoningText
	);
}

/** 流式尾巴 / live 标记会改变 groupTranscript 输出 —— 这类 opts 不进跨会话缓存。 */
function blockOptsLive(o: BlockOpts): boolean {
	return Boolean(o.isLoading || o.streamingText?.trim() || o.reasoningText?.trim());
}

/** per-session 缓存上限（LRU 淘汰最早写入的会话）。 */
const BLOCK_CACHE_LIMIT = 6;

function trimSessionCache(map: Map<string, unknown>, limit: number): void {
	while (map.size > limit) {
		const oldest = map.keys().next().value;
		if (oldest === undefined) {
			return;
		}
		map.delete(oldest);
	}
}

/** 冷会话装载等待态：占位沉底（与落地贴底一致）， brief 且不可交互。 */
function SessionPendingState({workspaceName}: {workspaceName: string}) {
	return (
		<div
			className="xy-chat-surface relative flex min-h-0 min-w-0 flex-1 flex-col"
			aria-busy="true"
		>
			<div className="flex min-h-0 flex-1 flex-col justify-end gap-2.5 overflow-hidden px-3 pb-10 sm:px-5 md:px-8">
				<div className="h-9 w-2/3 self-end animate-pulse rounded-2xl bg-black/[0.06]" />
				<div className="h-4 w-3/5 animate-pulse rounded-full bg-black/[0.04]" />
				<div className="h-4 w-4/5 animate-pulse rounded-full bg-black/[0.04]" />
			</div>
			<span className="sr-only">正在载入{workspaceName}的对话…</span>
		</div>
	);
}


export function MessageList({
	messages: messagesProp,
	streamingText: streamingTextProp,
	isLoading: isLoadingProp,
	statusText: statusTextProp,
	agentTasks: agentTasksProp,
}: MessageListProps) {
	const {
		smoothness,
		model,
		messages,
		messagesPending,
		agentTasks,
		activeId,
		isLoading,
		streamingSignal,
		streamingText,
		statusText,
		reasoningText,
		thoughtStartedAt,
		stopGeneration,
		anyStreaming,
		emptyQuipSeq,
		activeSpaceId,
		spaces,
	} = useMessageListStore({
		messages: messagesProp,
		streamingText: streamingTextProp,
		isLoading: isLoadingProp,
		statusText: statusTextProp,
		agentTasks: agentTasksProp,
	});

		const hover = useHoverScroll(100, {
				edgeFadeTop: true,
				edgeFadeTopSize: 40,
			});
		const scrollerRef = useRef<HTMLDivElement>(null);
			const contentRef = useRef<HTMLDivElement>(null);
		const pinOverlayRef = useRef<HTMLDivElement | null>(null);
		const messagesRef = useRef(messages);
		messagesRef.current = messages;
		const stickyLayoutMuteRef = useRef(false);
		const frameKeysRef = useRef<{
			scroll: string;
			topFade: string;
			rail: string;
			stuck: string;
		} | null>(null);

		if (!frameKeysRef.current) {
			frameKeysRef.current = {
				scroll: createFrameKey('message-scroll'),
				topFade: createFrameKey('message-top-fade'),
				rail: createFrameKey('message-rail'),
				stuck: createFrameKey('message-stuck'),
				};
		}

		/* 阶段1 灰度：自绘壁纸开启时在根节点打标，CSS 据此启用 pin 背景复刻。
		   主聊天与沉浸层会并存两个 MessageList 实例，attr 采用引用计数：
		   任一实例卸载不得删掉另一实例仍依赖的全局标记（冒烟 #6 根因）。 */
		useEffect(() => {
			acquireSelfWallpaper();
			return releaseSelfWallpaper;
		}, []);

		/** 视口与编辑簇共用（编辑锁 / 跟随尾部）。 */
		const editingViewportLockRef = useRef(false);
		const stickToBottom = useRef(true);
		const scrollScheduled = useRef(false);
		const streamingRef = useRef(false);
		const [forceMount, setForceMount] = useState<Record<string, true>>({});

		const syncTopFade = useCallback(() => {
			/* 顶 fade 叠层已撤；保留调度点以免 scroll/RO 接线再改一轮 */
		}, []);

		const scheduleTopFade = useCallback(() => {
			scheduleFrameRead(frameKeysRef.current!.topFade, syncTopFade);
		}, [syncTopFade]);

		const stickyBubblesOn = useSettingsStore(s => s.stickyBubbles === true);
		const {
			controller: stickyCtrl,
			editPortalHost,
			flushStuck,
			requestStuck,
			registerSticky: registerStickyCore,
			beginStickyEdit,
			endStickyEdit,
			setEditingId: setStickyEditingId,
			muteStickyLayoutSnap,
		} = useStickyPromptController({
			messagesRef,
			scrollerRef,
			contentRef,
	overlayRef: pinOverlayRef,
			streaming: Boolean(isLoading || streamingText),
			enabled: stickyBubblesOn,
			onLayoutMute: () => {
				stickyLayoutMuteRef.current = true;
				window.setTimeout(() => {
					stickyLayoutMuteRef.current = false;
				}, 80);
			},
		});
		const requestStuckRef = useRef(requestStuck);
		requestStuckRef.current = requestStuck;

		const groupedRef = useRef<{
		key: string;
		messages: ChatMessage[];
		opts: BlockOpts;
		blocks: TranscriptBlock[];
	} | null>(null);
	/** 跨会话切换的 settled 转录缓存：blocks 只依赖 messages 引用（无流式尾巴时）。 */
	const blocksBySessionRef = useRef(
		new Map<string, {messages: ChatMessage[]; blocks: TranscriptBlock[]}>(),
	);
	const roundsPrevRef = useRef<Round[] | null>(null);
	/** rounds 跨会话缓存：切回旧会话时 rounds 数组引用原样复用（RoundHost 全跳重渲）。 */
	const roundsBySessionRef = useRef(
		new Map<
			string,
			{
				blocks: TranscriptBlock[];
				agentTasks: typeof agentTasks;
				rounds: Round[];
			}
		>(),
	);

	const blocks = useMemo(() => {
		const key = activeId ?? '';
		const opts: BlockOpts = {
			streamingText,
			isLoading,
			statusText,
			reasoningText,
		};
		const prev = groupedRef.current;
		if (prev && prev.key === key && prev.messages === messages) {
			if (blockOptsSame(prev.opts, opts)) {
				return prev.blocks;
			}
			// messages 引用未变、只改流式尾巴 → O(尾) 补丁，不全量重分组。
			const patched = patchTranscriptTail(prev.blocks, opts);
			groupedRef.current = {key, messages, opts, blocks: patched};
			return patched;
		}
		// settled 转录只依赖 messages 引用：切回旧会话直接命中缓存。
		const cached = blocksBySessionRef.current.get(key);
		if (cached && cached.messages === messages && !blockOptsLive(opts)) {
			groupedRef.current = {key, messages, opts, blocks: cached.blocks};
			return cached.blocks;
		}
		const next = groupTranscript(messages, opts);
		groupedRef.current = {key, messages, opts, blocks: next};
		if (!blockOptsLive(opts)) {
			blocksBySessionRef.current.set(key, {messages, blocks: next});
			trimSessionCache(blocksBySessionRef.current, BLOCK_CACHE_LIMIT);
		}
		return next;
	}, [activeId, messages, streamingText, isLoading, statusText, reasoningText]);

	const rounds = useMemo(() => {
		const key = activeId ?? '';
		const cached = roundsBySessionRef.current.get(key);
		if (cached && cached.blocks === blocks && cached.agentTasks === agentTasks) {
			return cached.rounds;
		}
		const base = reuseRoundPrefix(
			roundsPrevRef.current,
			groupRounds(blocks),
		);
		const withTasks = roundsWithAgentTasks(base, agentTasks);
		roundsPrevRef.current = withTasks;
		roundsBySessionRef.current.set(key, {blocks, agentTasks, rounds: withTasks});
		trimSessionCache(roundsBySessionRef.current, BLOCK_CACHE_LIMIT);
		return withTasks;
	}, [activeId, blocks, agentTasks]);

	/** 多 Agent：仅 status 变化触发 layout 重算；高度靠 ResizeObserver。 */
	const agentTasksPinKey = useMemo(() => {
		if (!agentTasks.length) {
			return '';
		}
		return agentTasks.map(t => `${t.uid}:${t.status}`).join('|');
	}, [agentTasks]);

	const railItemsCacheRef = useRef<{
		messages: ChatMessage[];
		items: TurnRailItem[];
	} | null>(null);
	// P-SWITCH②：badge 按需计算。此前构建 railItems 时对每一轮做
	// collectLatestTodosFromItems 深扫（O(全部 items)），是 warm 切换的固定
	// 成本之一；badge 只在面板可见行展示，改为 TurnRail 对挂载行回调取用，
	// 缓存按 messages 引用失效（todos 变化必然伴随 messages 更新）。
	const badgeCacheRef = useRef<{
		messages: ChatMessage[];
		byRoundId: Map<string, string | undefined>;
	} | null>(null);
	const roundsIndexRef = useRef<{
		rounds: Round[];
		byId: Map<string, Round>;
	} | null>(null);
	const badgeVersionRef = useRef(0);
	const roundsRef = useRef(rounds);
	roundsRef.current = rounds;
	const railItems = useMemo((): TurnRailItem[] => {
		const cached = railItemsCacheRef.current;
		if (cached && cached.messages === messages) {
			return cached.items;
		}
		const out: TurnRailItem[] = [];
		for (const round of rounds) {
			if (!round.user) {
				continue;
			}
			out.push({
				id: round.id,
				label: round.user.text,
			});
		}
		railItemsCacheRef.current = {messages, items: out};
		return out;
	}, [messages, rounds]);
	// badgeVersion：messages 每次换代自增，驱动 TurnRail 重算挂载行 badge
	//（流式 token tick 不改 messages → 不自增 → TurnRail 全跳，与从前一致）。
	const badgeVersion = useMemo(() => ++badgeVersionRef.current, [messages]);
	const getBadge = useCallback((roundId: string): string | undefined => {
		const currentRounds = roundsRef.current;
		// rounds 换代（含会话切换）→ 重建 id 索引（浅 Map，一次性 O(rounds)）。
		let index = roundsIndexRef.current;
		if (!index || index.rounds !== currentRounds) {
			const byId = new Map<string, Round>();
			for (const round of currentRounds) {
				byId.set(round.id, round);
			}
			index = roundsIndexRef.current = {rounds: currentRounds, byId};
		}
		// badge 缓存按 messages 引用失效（todos 变化必然伴随 messages 更新）。
		let cache = badgeCacheRef.current;
		if (!cache || cache.messages !== messagesRef.current) {
			cache = badgeCacheRef.current = {
				messages: messagesRef.current,
				byRoundId: new Map(),
			};
		}
		if (cache.byRoundId.has(roundId)) {
			return cache.byRoundId.get(roundId);
		}
		let badge: string | undefined;
		const round = index.byId.get(roundId);
		if (round) {
			for (const block of round.rest) {
				if (block.kind !== 'turn') {
					continue;
				}
				const snap = collectLatestTodosFromItems(block.items);
				if (snap && snap.todos.length > 0) {
					const done = snap.todos.filter(
						t => t.status === 'completed',
					).length;
					badge = `${done}/${snap.todos.length}`;
				}
			}
		}
		cache.byRoundId.set(roundId, badge);
		return badge;
	}, []);
	const railItemsRef = useRef<TurnRailItem[]>([]);
	railItemsRef.current = railItems;
	const roundIds = useMemo(() => rounds.map(round => round.id), [rounds]);
	const roundIdsRef = useRef<readonly string[]>([]);
	roundIdsRef.current = roundIds;
	const windowApiRef = useRef<VirtualRoundListApi | null>(null);
	const forcedRoundIndices = useMemo(() => {
		const out = new Set<number>();
		for (let index = 0; index < rounds.length; index += 1) {
			if (forceMount[rounds[index]!.id]) {
				out.add(index);
			}
		}
		return out;
	}, [rounds, forceMount]);
	const ioAvailable = typeof IntersectionObserver !== 'undefined';
	// O(1) 签名（长度 + 首尾 id）：流式 token 每 tick 产生新 rounds 数组，
	// 全量 join 会随轮数线性放大；round 集合变化必然改变长度或首尾 id。
	const roundSignature = useMemo(
		() =>
			`${rounds.length}\u0000${rounds[0]?.id ?? ''}\u0000${rounds[rounds.length - 1]?.id ?? ''}`,
		[rounds],
	);

	const hasRows = blocks.length > 0;
	const streaming =
		Boolean(streamingText) || (isLoading && Boolean(statusText));
	streamingRef.current = streaming;
	const latestTurnId = useMemo(() => {
		for (let i = blocks.length - 1; i >= 0; i -= 1) {
			const b = blocks[i];
			if (b?.kind === 'turn') {
				return b.id;
			}
		}
		return null;
	}, [blocks]);
	const latestRoundIndex = Math.max(0, rounds.length - 1);
	const roundStreamLive = useMemo(
		() => ({
			roundSettled: !isLoading && !streamingText,
			streamingSignal,
			thoughtStartedAt,
			latestTurnId,
		}),
		[
			isLoading,
			streamingText,
			streamingSignal,
			thoughtStartedAt,
			latestTurnId,
		],
	);

	const viewport = useMessageListViewport({
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
	});

	const editing = useMessageListEditing({
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
	});

	const registerSticky = useCallback(
		(id: string, node: HTMLElement | null, editable: boolean) => {
			registerStickyCore(id, node, editable);
			scheduleTopFade();
		},
		[registerStickyCore, scheduleTopFade],
	);

	const {activeSessionId} = useMessageListRollbackStore();
	const cutPills = useRewindV3Store(s =>
		activeSessionId ? s.pillsBySession[activeSessionId] : undefined,
	);
	const loadCutPills = useRewindV3Store(s => s.loadPills);
	const rehydrateRewind = useRewindV3Store(s => s.rehydrate);
	// 未绑工作区的会话（默认空间未开目录 / 侧聊虚拟 space）对服务端 rewind
	// 端点必 400「session has no workspace」——pill 拉取与回溯重对齐均无意义，
	// 直接跳过，避免每次切会话/上屏都打一轮注定失败的请求（2026-09-05 E2E 排查）。
	const pillWorkspaceBound = useChatStore(s => {
		const ses = s.sessions.find(x => x.id === activeSessionId);
		if (!ses || ses.spaceId === SIDE_SPACE_ID) {
			return false;
		}
		const space = s.spaces.find(sp => sp.id === ses.spaceId);
		return Boolean(space?.rootPath?.trim());
	});
	useEffect(() => {
		if (activeSessionId && pillWorkspaceBound) {
			void loadCutPills(activeSessionId);
			// 重载后若是进行中回溯（未决态），按持久化 rewindId 重对齐（设计 §6.1 C3）。
			void rehydrateRewind(activeSessionId);
		}
	}, [activeSessionId, pillWorkspaceBound, loadCutPills, rehydrateRewind]);

	const workspaceName =
		spaces.find(s => s.id === activeSpaceId)?.name?.trim() || 'this project';
	const emptyQuip = useMemo(
		() => pickEmptyQuip(),
		[activeId, emptyQuipSeq],
	);

	if (!hasRows) {
		// 乐观切换：activeId 已就位但消息仍在后台装载 —— 渲染等待骨架，
		// 不能把冷会话误当空对话闪 EmptyState hero。
		if (messagesPending) {
			return <SessionPendingState workspaceName={workspaceName} />;
		}
		return <EmptyState workspaceName={workspaceName} emptyQuip={emptyQuip} />;
	}

	return (
		<EditPortalHostContext.Provider value={editPortalHost}>
			<div
				ref={editing.editRootRef}
				className="xy-chat-surface relative flex min-h-0 min-w-0 flex-1 flex-col"
				onMouseEnter={hover.onMouseEnter}
			onMouseLeave={hover.onMouseLeave}
		>
			<div className="relative min-h-0 min-w-0 flex-1">
						<div
							ref={viewport.setScrollerNode}
								className="xy-chat-surface xy-hover-scroll relative z-0 h-full min-h-0 min-w-0 overflow-y-auto overflow-x-clip"
								style={{overflowAnchor: 'none'}}
							>
														<div ref={contentRef} className="pt-1 pb-[min(18vh,9rem)]">
					<VirtualRoundList
						roundIds={roundIds}
						scrollElement={viewport.scrollerEl}
						contentRef={contentRef}
						smoothness={smoothness}
						sessionSwitching={viewport.sessionSwitching}
						forcedIndices={forcedRoundIndices}
						ioAvailable={ioAvailable}
						stickToBottomRef={stickToBottom}
						apiRef={windowApiRef}
						measureMuteRef={stickyLayoutMuteRef}
						renderRound={(roundIndex, {bypassRoundMountIo}) => {
							const round = rounds[roundIndex];
							if (!round) {
								return null;
							}
							const streamProps = roundStreamHostProps(
								roundIndex,
								latestRoundIndex,
								roundStreamLive,
							);
							const host = (
								<RoundHost
									key={round.id}
									round={round}
									roundIndex={roundIndex}
									roundsLength={rounds.length}
									smoothness={smoothness}
									forced={
										Boolean(forceMount[round.id]) || bypassRoundMountIo
									}
									ioAvailable={ioAvailable}
									root={viewport.scrollerEl}
										editingMessageId={editing.editingMessageId}
										editingText={editing.editingText}
										editingCaret={editing.editingCaret}
										beginEdit={editing.beginEdit}
										onEditTextChange={editing.setEditingText}
										editingSubmitting={editing.editingSubmitting}
										cancelEdit={editing.cancelEdit}
										submitEdit={editing.submitEdit}
										model={model}
										modelOpen={editing.modelOpen}
										modelMenuId={editing.modelMenuId}
										toggleModel={editing.toggleModel}
										closeModel={editing.closeModel}
										editingTextareaRef={editing.editingTextareaRef}
										promptEditRef={editing.promptEditRef}
										editingFilePickerOpenRef={editing.editingFilePickerOpenRef}
										editingFileInputRef={editing.editingFileInputRef}
										editingAttachments={editing.editingAttachments}
										editingExistingMediaRefs={editing.editingExistingMediaRefs}
										onEditAttachmentPick={editing.onEditAttachmentPick}
										onRemoveEditAttachment={editing.onRemoveEditAttachment}
										editingUploading={editing.editingUploading}
										editModelMenuRef={editing.editModelMenuRef}
										anyStreaming={anyStreaming}
										stopGeneration={stopGeneration}
										resizeEditingTextarea={editing.resizeEditingTextarea}
										lockEditFlow={
											stickyBubblesOn &&
											editing.stickyEditFlowLockRef.current &&
											editing.editingMessageId === round.user?.id
										}
										editFlowHeight={editing.editFlowHeight}
										editClosing={
											editing.editClosing && editing.editingMessageId === round.user?.id
										}
										latestTurnId={streamProps.latestTurnId}
										roundSettled={streamProps.roundSettled}
										streamingSignal={streamProps.streamingSignal}
										thoughtStartedAt={streamProps.thoughtStartedAt}
										registerSticky={registerSticky}
									/>
								);
								const pills = findRoundPills(round, cutPills);
								const pillBefore = pills.before;
								const pillAfter = pills.after;
								if (!pillBefore && !pillAfter) {
									return host;
								}
								const pillNode = (pill: RewindPill) => (
									<RewindCutPill
										digest={pill.editedDigest}
										removedRows={pill.removedRows}
										onClick={() =>
											useRewindV3Store
												.getState()
												.openPillDialog(activeSessionId ?? '', pill)
										}
									/>
								);
								return (
									<div key={round.id} className="flex flex-col">
										{pillBefore ? pillNode(pillBefore) : null}
										{host}
										{pillAfter ? pillNode(pillAfter) : null}
									</div>
								);
							}}
						/>
									</div>
					</div>

					{/* 吸顶 pin 层：与 scroller 同级，绘制在壁纸之上而非 transcript 之上。
					    吸顶 chip 已 invisible，此处以发送框同款表面重建同文本 chip，
					    配 content 打孔 → 内容不透出、壁纸透出。DOM 由 applyStuck 同步写入。 */}
					<div
						ref={pinOverlayRef}
						className="pointer-events-none absolute inset-0 z-20 overflow-visible"
						aria-hidden="true"
					/>

				</div>

					<TurnRail
						items={railItems}
						activeId={viewport.railActiveId}
						onJump={viewport.jumpToRound}
						getBadge={getBadge}
						badgeVersion={badgeVersion}
					/>
					<RollbackDialogs activeSessionId={activeSessionId} />
			</div>
		</EditPortalHostContext.Provider>
		);
}
