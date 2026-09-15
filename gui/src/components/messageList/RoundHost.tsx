/**
 * 归属：从 components/MessageList.tsx 巨石拆分而来（spec m3: RoundHost，2026 拆分）。
 * 拆分脚本 dismantle-messagelist.cjs 已归档至 [过程]/legacy/，本文件此后为手工维护。
 * 代码块自 components/MessageList.tsx 原样迁移，行为不变。
 */
import {
	memo,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	type MouseEvent,
	type MutableRefObject,
} from 'react';
import {
	type TranscriptBlock,
} from '@/lib/groupTranscript';
import {
	shouldMountRound,
} from '@/lib/roundWindow';
import {
	finalRoundProseMessageIds,
	mergeTurnActivity,
} from '@/lib/toolActivity';
import {
	type ChatMessage,
} from '@/lib/types';
import {
	type DraftAttachment,
} from '@/lib/composerDrafts';
import {
	cn,
} from '@/lib/utils';
import {
	ActivityLog,
} from '../ActivityLog';
import {
	ExpandPanel,
} from '../activity/ExpandPanel';
import {
	AssistantTurn,
} from '../AssistantTurn';
import {
	SplitChevron,
} from '../activity/SplitChevron';
import {
	MessageBubble,
} from '../MessageBubble';
import {
	RoundMount,
} from '../RoundMount';
import {
	PROMPT_CHIP_MAX_PX,
	STICKY_TOP_PX,
} from '../sticky';
import {
	Round,
} from './types';
import {
	PROMPT_X,
} from './groupRounds';
import {
	PromptBubble,
} from './PromptBubble.tsx';

export type RoundHostProps = {
	round: Round;
	roundIndex: number;
	roundsLength: number;
	smoothness: boolean;
	forced: boolean;
	ioAvailable: boolean;
	root: HTMLElement | null;
	editingMessageId: string | null;
		editingText: string;
	editingCaret: number | null;
	onEditTextChange: (text: string) => void;

	editingSubmitting: boolean;
	cancelEdit: () => void;
		submitEdit: () => void;
	beginEdit: (message: Pick<ChatMessage, 'id' | 'text' | 'mediaRefs'>, event?: MouseEvent<HTMLDivElement>) => void;
promptEditRef: MutableRefObject<HTMLDivElement | null>;
	editingFilePickerOpenRef: MutableRefObject<boolean>;
	/** 吸顶编辑流内锁高 */
	lockEditFlow?: boolean;
	/** 流内占位高度（展开后可跟气泡） */
	editFlowHeight?: number;
	/** 取消中：底栏先收 */
	editClosing?: boolean;
	editingFileInputRef: MutableRefObject<HTMLInputElement | null>;
	editingAttachments: DraftAttachment[];
			editingExistingMediaRefs: string[];

	onEditAttachmentPick: (files: FileList | File[] | null) => void;
	onRemoveEditAttachment: (id: string) => void;
		editingUploading: boolean;
	model: string;
	modelOpen: boolean;
	modelMenuId: string;
	toggleModel: () => void;
		closeModel: () => void;
		editingTextareaRef: MutableRefObject<HTMLTextAreaElement | null>;
		editModelMenuRef: MutableRefObject<HTMLDivElement | null>;
		anyStreaming: boolean;
	stopGeneration: () => void;
	resizeEditingTextarea: () => void;

	latestTurnId: string | null;
	roundSettled: boolean;
	streamingSignal: boolean;
	thoughtStartedAt: number | null;
	registerSticky: (id: string, node: HTMLElement | null, editable: boolean) => void;
};

export function roundHostPropsAreEqual(prev: RoundHostProps, next: RoundHostProps): boolean {
	const staticEqual =
		prev.round === next.round &&
		prev.roundIndex === next.roundIndex &&
		prev.roundsLength === next.roundsLength &&
		prev.smoothness === next.smoothness &&
		prev.forced === next.forced &&
		prev.ioAvailable === next.ioAvailable &&
		prev.root === next.root &&
		prev.latestTurnId === next.latestTurnId &&
		prev.roundSettled === next.roundSettled &&
		prev.streamingSignal === next.streamingSignal &&
		prev.thoughtStartedAt === next.thoughtStartedAt &&
		prev.registerSticky === next.registerSticky;
	if (!staticEqual) {
		return false;
	}

	const prevEditing = prev.editingMessageId === prev.round.user?.id;
	const nextEditing = next.editingMessageId === next.round.user?.id;
	if (prevEditing !== nextEditing) {
		return false;
	}
	if (!nextEditing) {
		return true;
	}

	return (
		prev.editingText === next.editingText &&
		prev.editingCaret === next.editingCaret &&
		prev.editingSubmitting === next.editingSubmitting &&
		prev.onEditTextChange === next.onEditTextChange &&
		prev.cancelEdit === next.cancelEdit &&
		prev.submitEdit === next.submitEdit &&
		prev.model === next.model &&
		prev.modelOpen === next.modelOpen &&
		prev.modelMenuId === next.modelMenuId &&
		prev.toggleModel === next.toggleModel &&
		prev.closeModel === next.closeModel &&
		prev.editingTextareaRef === next.editingTextareaRef &&
			prev.editModelMenuRef === next.editModelMenuRef &&
			prev.editingFileInputRef === next.editingFileInputRef &&
			prev.editingAttachments === next.editingAttachments &&
							(prev.editingExistingMediaRefs === next.editingExistingMediaRefs ||
					(prev.editingExistingMediaRefs.length === next.editingExistingMediaRefs.length &&
						prev.editingExistingMediaRefs.every((ref, index) => ref === next.editingExistingMediaRefs[index]))) &&

			prev.onEditAttachmentPick === next.onEditAttachmentPick &&
			prev.onRemoveEditAttachment === next.onRemoveEditAttachment &&
				prev.editingUploading === next.editingUploading &&
			prev.anyStreaming === next.anyStreaming &&
		prev.stopGeneration === next.stopGeneration &&
		prev.resizeEditingTextarea === next.resizeEditingTextarea &&
		prev.lockEditFlow === next.lockEditFlow &&
		prev.editFlowHeight === next.editFlowHeight &&
		prev.editClosing === next.editClosing
	);
}

export const RoundHost = memo(function RoundHost({
	round,
	roundIndex,
	roundsLength,
	smoothness,
	forced,
	ioAvailable,
		root,
		editingMessageId,
			editingText,
		onEditTextChange,

	editingSubmitting,
	cancelEdit,
			submitEdit,
		beginEdit,
		model,
		modelOpen,
		modelMenuId,
		toggleModel,
			closeModel,
				editingTextareaRef,
					editModelMenuRef,
promptEditRef,
		editingFilePickerOpenRef,
			editingFileInputRef,
			editingAttachments,
			editingExistingMediaRefs,
			onEditAttachmentPick,
			onRemoveEditAttachment,
			editingUploading,
			anyStreaming,
		stopGeneration,
		resizeEditingTextarea,
		lockEditFlow = false,
		editFlowHeight = PROMPT_CHIP_MAX_PX,
		editClosing = false,
	latestTurnId,
	roundSettled,
	streamingSignal,
	thoughtStartedAt,
	registerSticky,
}: RoundHostProps) {
		// 挂载决策归 VirtualRoundList 的窗口（视口 ± overscan ∪ 最新轮 ∪ 强制轮）。
		// 不再因 sessionSwitching 强制全挂 —— 那是长对话切换瞬间渲染卡顿的主因。
		// shouldMountRound 保留为兜底（强制轮 / 关闭流畅 / 无 IO 时全挂）。
		const always = shouldMountRound({
			index: roundIndex,
			total: roundsLength,
			smoothness,
			forced,
			ioAvailable,
		});
	const stickyRef = useCallback(
		(node: HTMLElement | null) => {
			if (round.user) {
				registerSticky(round.user.id, node, round.user.source !== 'remote');
			}
		},
		[registerSticky, round.user?.id, round.user?.source],
	);
	const editPrompt = useCallback(
		(event?: MouseEvent<HTMLDivElement>) => {
			const user = round.user;
			if (user) {
				beginEdit(user, event);
			}
		},
		[beginEdit, round.user],
	);

	// 任务收尾：整段工作流默认折叠进 done on；展开后回看交错明细
	const turnBlocks = useMemo(
		() =>
			round.rest.filter(
				(block): block is Extract<TranscriptBlock, {kind: 'turn'}> =>
					block.kind === 'turn',
			),
		[round],
	);
	const mergedActivity = useMemo(() => {
		if (!roundSettled) {
			return null;
		}
		return mergeTurnActivity(turnBlocks);
	}, [roundSettled, turnBlocks]);
	const finalProseIds = useMemo(
		() =>
			mergedActivity ? finalRoundProseMessageIds(turnBlocks) : null,
		[mergedActivity, turnBlocks],
	);
	const [workflowOpen, setWorkflowOpen] = useState(false);
	const prevMergedRef = useRef<string | null>(null);
	useEffect(() => {
		const key = mergedActivity ? `${round.id}:${mergedActivity.summary}` : null;
		if (prevMergedRef.current !== key) {
			prevMergedRef.current = key;
			setWorkflowOpen(false);
		}
	}, [mergedActivity, round.id]);

	/** live → done on：仅本轮刚收尾时播放交叉过渡；历史轮次直接到位 */
	const sawLiveRef = useRef(false);
	const [settlePhase, setSettlePhase] = useState<'idle' | 'collapsing' | 'done'>(
		'idle',
	);
	useEffect(() => {
		if (!roundSettled) {
			sawLiveRef.current = true;
			setSettlePhase('idle');
		}
	}, [roundSettled]);
	useEffect(() => {
		if (!mergedActivity) {
			setSettlePhase('idle');
			return;
		}
		if (!smoothness || !sawLiveRef.current) {
			setSettlePhase('done');
			return;
		}
		sawLiveRef.current = false;
		setSettlePhase('collapsing');
		const t = window.setTimeout(() => setSettlePhase('done'), 480);
		return () => window.clearTimeout(t);
	}, [mergedActivity, smoothness]);

	const settling = settlePhase === 'collapsing';
	const showDoneChrome = Boolean(mergedActivity) && settlePhase !== 'idle';
	const activitySettled = settlePhase === 'done';

	const renderTurn = (
		block: Extract<TranscriptBlock, {kind: 'turn'}>,
		opts: {
			suppressActivity: boolean;
			visibleProseIds: Set<string> | null;
			includeAgents: boolean;
		},
	) => (
		<div key={`${block.id}-${opts.suppressActivity ? 'final' : 'full'}`}>
			<AssistantTurn
				turnId={block.id}
				items={block.items}
				streaming={block.streaming}
				thinking={block.thinking}
				active={block.active}
				roundSettled={roundSettled}
				isLatestTurn={block.id === latestTurnId}
				hideActivityHeader={
					!roundSettled &&
					!activitySettled &&
					block.id !== latestTurnId
				}
				agentTasks={
					opts.includeAgents && round.agentTasks.length > 0
						? round.agentTasks
						: undefined
				}
				streamingSignal={streamingSignal && Boolean(block.streaming)}
				suppressActivity={opts.suppressActivity}
				visibleProseIds={opts.visibleProseIds}
				thoughtStartedAt={block.active ? thoughtStartedAt : null}
			/>
		</div>
	);

	return (
		<RoundMount
			roundId={round.id}
			always={always}
			root={root}
			cacheHeight={roundSettled}
		>
				{round.user ? (
						<div
							ref={stickyRef}
							className={cn('xy-prompt-sticky group/msg', PROMPT_X)}
							style={{
								zIndex: 40 + roundIndex,
								top: STICKY_TOP_PX,
							}}
						>
							<PromptBubble
								text={round.user.text}
								mediaRefs={round.user.mediaRefs}
								editable={round.user.source !== 'remote'}
								isEditing={editingMessageId === round.user.id}
								onEdit={editPrompt}
								rise={
									smoothness &&
									roundIndex === roundsLength - 1 &&
									Date.now() - round.user.createdAt < 900
								}
								editingText={editingText}
								onEditTextChange={onEditTextChange}
								editingSubmitting={editingSubmitting}
								cancelEdit={cancelEdit}
								submitEdit={submitEdit}
								model={model}
								modelOpen={modelOpen}
								modelMenuId={modelMenuId}
								toggleModel={toggleModel}
								closeModel={closeModel}
								editingTextareaRef={editingTextareaRef}
								promptEditRef={promptEditRef}
								editingFilePickerOpenRef={editingFilePickerOpenRef}
								editingFileInputRef={editingFileInputRef}
								editingAttachments={editingAttachments}
								editingExistingMediaRefs={editingExistingMediaRefs}
								onEditAttachmentPick={onEditAttachmentPick}
								onRemoveEditAttachment={onRemoveEditAttachment}
								editingUploading={editingUploading}
								editModelMenuRef={editModelMenuRef}
								anyStreaming={anyStreaming}
								stopGeneration={stopGeneration}
								resizeEditingTextarea={resizeEditingTextarea}
								lockEditFlow={
									lockEditFlow && editingMessageId === round.user.id
								}
								editFlowHeight={editFlowHeight}
								editClosing={
									editClosing && editingMessageId === round.user.id
								}
							/>
						</div>
				) : null}
					<div
					className={cn(
						'xy-round-transcript-layer pb-2.5',
						settling && 'is-settling',
					)}
				>
				{showDoneChrome && mergedActivity ? (
					<div
						key={`done-on-${round.id}`}
						className={cn(
							'xy-done-on-wrap px-3 pt-2 sm:px-5 md:px-8',
							settling && 'is-settle-in',
						)}
					>
						<div className="mx-auto max-w-3xl">
							<button
								type="button"
								className="xy-split-head xy-done-on-head group/head"
								aria-expanded={workflowOpen}
								onClick={() => setWorkflowOpen(v => !v)}
							>
								<span className="xy-split-head-lead">
									<span className="xy-split-head-label xy-split-summary">
										{mergedActivity.summary}
									</span>
									<SplitChevron open={workflowOpen} />
								</span>
								<span className="xy-split-head-meta">
									<span className="xy-done-extra">
										{mergedActivity.steps.length} steps
										{mergedActivity.diffs.add > 0 ||
										mergedActivity.diffs.del > 0 ? (
											<>
												{' · '}
												{mergedActivity.diffs.add > 0 ? (
													<span className="text-ok">
														+{mergedActivity.diffs.add}
													</span>
												) : null}
												{mergedActivity.diffs.del > 0 ? (
													<span className="text-danger">
														-{mergedActivity.diffs.del}
													</span>
												) : null}
											</>
										) : null}
									</span>
								</span>
							</button>
							{/* 中间工作流：合并步骤轨，无旁白、无分段顶栏 */}
							<ExpandPanel
								open={workflowOpen}
								className="xy-workflow-fold"
								innerClassName="xy-activity-detail-inner"
							>
								<ActivityLog
									summary={`${mergedActivity.steps.length} steps`}
									diffs={mergedActivity.diffs}
									steps={mergedActivity.steps}
									expanded
									hideHeader
									active={false}
									onToggle={() => undefined}
								/>
							</ExpandPanel>
						</div>
					</div>
				) : null}
				{/* 进行中：完整交错；收尾折叠：仅最终回复 */}
				{round.rest.map(block => {
					if (block.kind === 'system') {
						if (activitySettled) {
							return null;
						}
						return (
							<div key={block.message.id}>
								<MessageBubble message={block.message} />
							</div>
						);
					}
					if (block.kind === 'turn') {
						if (mergedActivity && activitySettled) {
							return renderTurn(block, {
								suppressActivity: true,
								visibleProseIds: finalProseIds,
								includeAgents: true,
							});
						}
						return renderTurn(block, {
							suppressActivity: false,
							visibleProseIds: null,
							includeAgents: true,
						});
					}
					return null;
				})}
				</div>
			</RoundMount>
	);

	}, roundHostPropsAreEqual);

/**
 * sticky push 在 scroller 内保持原生吸附
 * 吸顶时：隐藏流内 chip，打孔使真实 L0 显示，在 overlay pin 绘制
 * 相同 chip（合成在壁纸之上，而非 transcript）。
 */
