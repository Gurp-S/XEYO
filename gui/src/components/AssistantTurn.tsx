import {memo, useCallback, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent} from 'react';
import type {MultiAgentTaskView} from '@/lib/api';
import type {ChatMessage} from '@/lib/types';
import {
	streamingSignalEligible,
	streamingTextSignal,
} from '@/lib/streamSignal';
import {useSignals} from '@preact/signals-react/runtime';
import type {ToolView, TurnItem} from '@/lib/groupTranscript';
import {
	appendLiveThoughtStep,
	collectChangedFilesFromItems,
	mergeChangedFilesWithPaths,
	normalizeActivitySteps,
	segmentTurn,
	type ActivityStep,
	type DiffStat,
	type TurnSegment,
} from '@/lib/toolActivity';
import {isProcessNarration} from '@/lib/processNarration';
import {stripXmlToolCallsForDisplay} from '@/lib/stripXmlToolCalls';
import {stripAgentAnchor} from '@/lib/agentAnchor';
import {assistantCopyMenuItems} from '@/lib/contextMenus';
import {
	countAgentActivitySteps,
} from '@/lib/agentCardLayout';
import {ActivityLog} from './ActivityLog';
import {AgentDoneBars} from './AgentDoneBars';
import {FilesChanged} from './FilesChanged';
import {StreamingMarkdown} from './StreamingMarkdown';
import {showContextMenu} from './ui/ContextMenu';
import {activityStepsEqual, multiAgentTaskViewsEqual} from '@/lib/workflowEquality';
type Props = {
	turnId: string;
	items: TurnItem[];
	streaming?: string;
	thinking?: string;
	active: boolean;
	/** 任意回复进行中时为 false。 */
	roundSettled?: boolean;
	/** 仅最新轮次可拥有 Files Changed；下次用户发送会销毁它。 */
	isLatestTurn?: boolean;
	/** 实验开关：仅纯文本流使用 Signals 直接更新 Text 节点。 */
	streamingSignal?: boolean;
	/**
	 * 本轮 Agent 工具对应的侧链入口（样式不变）。
	 * 流程与普通工具一致：思考 → 工具 → 继续回复；不再按锚点切「分配|子agent|总结」。
	 */
	agentTasks?: MultiAgentTaskView[];
	/** 任务收尾（最后一轮为无 tool 的纯文本回复且已 settle）时，
	 * MessageList 会把整个 submit 的工具合并成一个聚合层；
	 * 此时隐藏本轮内部的活动块，避免同一批步骤出现两份。
	 */
	suppressActivity?: boolean;
	/** 任务收尾时仅展示最终 prose（中间说明隐藏进折叠 activity）。 */
	visibleProseIds?: Set<string> | null;
	/** 当前思考阶段起始时刻（live Thought 步骤）。 */
	thoughtStartedAt?: number | null;
	/** 模型请求重试状态，展示在当前回合的 Working 轨迹中。 */
	workflowStatusText?: string;
	/**
	 * 进行中整轮只保留最新 turn 的 Working 顶栏；
	 * 更早 turn 的 activity 全部 hideHeader，避免叠多条折叠头。
	 */
	hideActivityHeader?: boolean;
};

/** 展示前去掉遗留锚点注释，避免空白/残片。 */
function displayProse(text: string): string {
	return stripAgentAnchor(stripXmlToolCallsForDisplay(text));
}

/** 完整的诊断签名；渲染路径使用结构比较，避免拼接超长 tool payload。 */
export function toolsFingerprint(items: TurnItem[]): string {
	return JSON.stringify(
		items.flatMap(item =>
			item.kind === 'tool'
				? [[
						item.tool.id,
						item.tool.toolUseId,
						item.tool.name,
						item.tool.input,
						item.tool.result,
						item.tool.status,
						item.tool.waiting,
						item.tool.createdAt,
						item.tool.reasoningBefore,
						item.tool.thoughtMs,
					]]
				: [],
		),
	);
}

export function proseFingerprint(items: TurnItem[]): string {
	return JSON.stringify(
		items.flatMap(item =>
			item.kind === 'assistant'
				? [[item.message.id, item.message.text, item.message.isThought, item.message.createdAt]]
				: [],
		),
	);
}

type TurnItemSnapshot =
	| {
			kind: 'assistant';
			id: string;
			text: string;
			isThought?: boolean;
			createdAt: number;
	  }
	| {
			kind: 'tool';
			id: string;
			toolUseId?: string;
			name: string;
			input: string;
			result: string;
			status: ToolView['status'];
			waiting?: boolean;
			createdAt: number;
			reasoningBefore?: string;
			thoughtMs?: number;
	  };

function snapshotTurnItems(items: TurnItem[]): TurnItemSnapshot[] {
	return items.map(item =>
		item.kind === 'assistant'
			? {
					kind: 'assistant',
					id: item.message.id,
					text: item.message.text,
					isThought: item.message.isThought,
					createdAt: item.message.createdAt,
				}
			: {
					kind: 'tool',
					id: item.tool.id,
					toolUseId: item.tool.toolUseId,
					name: item.tool.name,
					input: item.tool.input,
					result: item.tool.result,
					status: item.tool.status,
					waiting: item.tool.waiting,
					createdAt: item.tool.createdAt,
					reasoningBefore: item.tool.reasoningBefore,
					thoughtMs: item.tool.thoughtMs,
				},
	);
}

function snapshotMatchesItems(snapshot: TurnItemSnapshot[], items: TurnItem[]): boolean {
	if (snapshot.length !== items.length) return false;
	for (let i = 0; i < snapshot.length; i += 1) {
		const saved = snapshot[i]!;
		const item = items[i]!;
		if (saved.kind !== item.kind) return false;
		if (item.kind === 'assistant') {
			if (
				saved.kind !== 'assistant' ||
				saved.id !== item.message.id ||
				saved.text !== item.message.text ||
				saved.isThought !== item.message.isThought ||
				saved.createdAt !== item.message.createdAt
			) return false;
		} else if (
			saved.kind !== 'tool' ||
			saved.id !== item.tool.id ||
			saved.toolUseId !== item.tool.toolUseId ||
			saved.name !== item.tool.name ||
			saved.input !== item.tool.input ||
			saved.result !== item.tool.result ||
			saved.status !== item.tool.status ||
			saved.waiting !== item.tool.waiting ||
			saved.createdAt !== item.tool.createdAt ||
			saved.reasoningBefore !== item.tool.reasoningBefore ||
			saved.thoughtMs !== item.tool.thoughtMs
		) {
			return false;
		}
	}
	return true;
}

const AssistantBody = memo(function AssistantBody({
	text,
}: {
	text: string;
	streaming?: boolean;
}) {
	const cleaned = displayProse(text);
	if (!cleaned.trim()) {
		return null;
	}
	// 与流式同一引擎（final），settle 不换 MarkdownView 树。
	return <StreamingMarkdown text={cleaned} final codeAutoCollapse />;
});

const StreamingBody = memo(function StreamingBody({text}: {text: string}) {
	return <StreamingMarkdown text={displayProse(text)} />;
});

const StreamingSignalBody = memo(function StreamingSignalBody() {
	useSignals();
	const text = displayProse(streamingTextSignal.value);
	if (!streamingSignalEligible.value) {
		return <StreamingBody text={text} />;
	}
	return <StreamingMarkdown text={text} />;
});

function proseMessagesEqual(a: ChatMessage[], b: ChatMessage[]): boolean {
	if (a.length !== b.length) {
		return false;
	}
	for (let i = 0; i < a.length; i += 1) {
		if (
			a[i]!.id !== b[i]!.id ||
			a[i]!.text !== b[i]!.text ||
			a[i]!.isThought !== b[i]!.isThought
		) {
			return false;
		}
	}
	return true;
}

const ProseBlock = memo(
	function ProseBlock({messages}: {messages: ChatMessage[]}) {
		const visible = messages.filter(m => !m.isThought);
		if (visible.length === 0) {
			return null;
		}
		const markdown = visible
			.map(m => displayProse(m.text))
			.filter(Boolean)
			.join('\n\n');
		const onContextMenu = (event: ReactMouseEvent) => {
			if (!markdown.trim()) {
				return;
			}
			showContextMenu(event, assistantCopyMenuItems(markdown), '助手回复');
		};
		return (
			<div className="space-y-2" onContextMenu={onContextMenu}>
				{visible.map(m => (
					<AssistantBody key={m.id} text={m.text} />
				))}
			</div>
		);
	},
	(prev, next) => proseMessagesEqual(prev.messages, next.messages),
);

type ActivityBlockProps = {
	segId: string;
	summary: string;
	diffs: DiffStat;
	steps: ActivityStep[];
	active: boolean;
	startedAt?: number | null;
	/** 仅首段显示 Working；后续段只画步骤轨 */
	hideHeader?: boolean;
	/** 由 AssistantTurn 共享：进行中强制开，否则跟用户折叠 */
	expanded: boolean;
	onToggle: () => void;
	/** 进行中：Delegated 步骤旁就近挂子 Agent 卡片 */
	inlineAgentTasks?: MultiAgentTaskView[];
	/** 本段任务在全局 agentTasks 中的序号起点 */
	agentIndexBase?: number;
	workflowStatusText?: string;
};

/** 活动块：进行中强制展开；settle 后默认仍开，仅用户手动折。 */
export const ActivityBlock = memo(
	function ActivityBlock({
		segId: _segId,
		summary,
		diffs,
		steps,
		active: turnActive,
		startedAt = null,
		hideHeader = false,
		expanded,
		onToggle,
		inlineAgentTasks,
		agentIndexBase = 0,
		workflowStatusText,
	}: ActivityBlockProps) {
		const stepLive = steps.some(s => s.running);
		const inProgress = Boolean(turnActive || stepLive);
		const displaySteps = useMemo(
			() => normalizeActivitySteps(steps, stepLive),
			[steps, stepLive],
		);

		return (
			<div className="xy-enter-fade">
				<ActivityLog
					summary={summary}
					diffs={diffs}
					steps={displaySteps}
					expanded={expanded}
					active={inProgress}
					startedAt={startedAt}
					hideHeader={hideHeader}
					onToggle={onToggle}
				inlineAgentTasks={inlineAgentTasks}
				agentIndexBase={agentIndexBase}
				workflowStatusText={workflowStatusText}
			/>
			</div>
		);
	},
	(prev, next) =>
		prev.segId === next.segId &&
		prev.active === next.active &&
		prev.summary === next.summary &&
		prev.startedAt === next.startedAt &&
		prev.hideHeader === next.hideHeader &&
		prev.expanded === next.expanded &&
		prev.onToggle === next.onToggle &&
		prev.agentIndexBase === next.agentIndexBase &&
		prev.workflowStatusText === next.workflowStatusText &&
		prev.diffs.add === next.diffs.add &&
		prev.diffs.del === next.diffs.del &&
		activityStepsEqual(prev.steps, next.steps) &&
		multiAgentTaskViewsEqual(prev.inlineAgentTasks, next.inlineAgentTasks),
);

/**
 * 轮次布局：assistant prose 始终可见；tools 折叠进 activity。
 * 流式更新在 tool fingerprint 稳定时跳过 activity 重渲染。
 */
function AssistantTurnInner({
	turnId,
	items,
	streaming,
	thinking,
	active,
	roundSettled,
	isLatestTurn,
	streamingSignal = false,
	agentTasks,
	suppressActivity = false,
	visibleProseIds = null,
	thoughtStartedAt = null,
	workflowStatusText = '',
	hideActivityHeader = false,
}: Props) {

	const segmentsCache = useRef<{
		snapshot: TurnItemSnapshot[];
		segments: TurnSegment[];
	} | null>(null);
	if (
		!segmentsCache.current ||
		!snapshotMatchesItems(segmentsCache.current.snapshot, items)
	) {
		segmentsCache.current = {
			snapshot: snapshotTurnItems(items),
			segments: segmentTurn(items),
		};
	}
	const itemSnapshot = segmentsCache.current.snapshot;
	const segments = segmentsCache.current.segments;

	const changedFiles = useMemo(() => {
		const fromTools = collectChangedFilesFromItems(items);
		const fromAgents =
			agentTasks?.flatMap(t => t.filesTouched ?? []) ?? [];
		return mergeChangedFilesWithPaths(fromTools, fromAgents);
	}, [itemSnapshot, agentTasks]);

	const liveThoughtReady =
		active &&
		thoughtStartedAt != null &&
		Boolean(thinking?.trim()) &&
		!segments.some(
			seg => seg.kind === 'activity' && seg.steps.some(s => s.running),
		);

	// 有 reasoning 内容即展示 Thinking；工具 running 时改由已落盘 Thought 行承接
	const showLiveThought = liveThoughtReady;

	const hideNarration = Boolean(roundSettled || !active);

	const shouldRender = !(
		items.length === 0 &&
		!streaming &&
		!thinking &&
		!agentTasks?.length &&
		!active
	);

	// 整轮结束后再出 Changes，避免盖住还在流式的正文。
	const showFilesChanged =
		isLatestTurn && roundSettled && changedFiles.length > 0;

	const hasActivity = segments.some(seg => seg.kind === 'activity');

	// 首个工具/推理到达前也显示当前模型阶段；工具到达后复用同一 rail key。
	const displaySegments: TurnSegment[] = useMemo(() => {
		if (suppressActivity || hasActivity || (!showLiveThought && !active)) {
			return segments;
		}
		const liveSteps = showLiveThought
			? appendLiveThoughtStep([], {
					active: true,
					since: thoughtStartedAt,
					content: thinking,
				})
			: [];
		return [
			{
				kind: 'activity',
				id: 'act-live',
				steps: liveSteps,
				summary: 'Working…',
				diffs: {add: 0, del: 0},
			},
		];
	}, [
		segments,
		suppressActivity,
		hasActivity,
		showLiveThought,
		active,
		thoughtStartedAt,
		thinking,
	]);

	const displayFirstActivityIdx = displaySegments.findIndex(
		seg => seg.kind === 'activity',
	);
	const displayLastActivityIdx = displaySegments.findLastIndex(
		seg => seg.kind === 'activity',
	);

	// 整轮共用一顶栏折叠：进行中强制展开；settle 后默认开，仅用户手动折
	const [railOpen, setRailOpen] = useState(true);
	const railExpanded = Boolean(active) || railOpen;
	const onRailToggle = useCallback(() => {
		if (active) {
			return;
		}
		setRailOpen(v => !v);
	}, [active]);
	// Keep every hook above this gate: an empty turn can become active before its
	// first token, so returning before displaySegments/useState would change hook order.
	if (!shouldRender) return null;

	const hasAgents = Boolean(agentTasks?.length);
	/** 结束后：卡片在 Done 下、主回复上；进行中：按段切片挂到对应 Agent 步骤旁。 */
	const agentsAtTop = hasAgents && Boolean(roundSettled || suppressActivity);
	const agentsInline = hasAgents && !agentsAtTop;
	/** 各 activity 段内 Agent 步骤数（含 Failed），串行跨段一对一。 */
	const agentCountsBySeg = displaySegments.map(seg =>
		seg.kind === 'activity' ? countAgentActivitySteps(seg.steps) : 0,
	);

	return (
		<div className="px-3 py-2 sm:px-5 md:px-8">
			<div className="mx-auto max-w-3xl space-y-2">
				{/* 聚合收尾：卡片在主回复前（勿与进行中 inline 同时挂） */}
				{suppressActivity && hasAgents && agentTasks ? (
					<AgentDoneBars tasks={agentTasks} />
				) : null}
				{displaySegments.map((seg: TurnSegment, segIdx) => {
					if (seg.kind === 'prose') {
						let messages =
							visibleProseIds != null
								? seg.messages.filter(m => visibleProseIds.has(m.id))
								: seg.messages;
						if (hideNarration) {
							messages = messages.filter(
								m => !isProcessNarration(m.text),
							);
						}
						if (messages.length === 0) {
							return null;
						}
						return (
							<ProseBlock
								key={seg.messages.map(m => m.id).join('-')}
								messages={messages}
							/>
						);
					}
					if (suppressActivity) {
						return null;
					}
					const steps =
						showLiveThought && segIdx === displayLastActivityIdx
							? appendLiveThoughtStep(seg.steps, {
									active: true,
									since: thoughtStartedAt,
									content: thinking,
								})
							: seg.steps;
					const agentOffset = agentCountsBySeg
						.slice(0, segIdx)
						.reduce((a, b) => a + b, 0);
					const agentInSeg = countAgentActivitySteps(steps);
					const segTasks =
						agentsInline && agentTasks && agentInSeg > 0
							? agentTasks.slice(agentOffset, agentOffset + agentInSeg)
							: undefined;
					const isPrimaryRail = segIdx === displayFirstActivityIdx;
					return (
						<div
							key={
								isPrimaryRail
									? `${turnId}-rail`
									: `${turnId}-${seg.id}`
							}
							className="space-y-2"
						>
							<ActivityBlock
								segId={seg.id}
								summary={seg.summary}
								diffs={seg.diffs}
								steps={steps}
								active={active}
						startedAt={thoughtStartedAt}
						workflowStatusText={
							segIdx === displayFirstActivityIdx
								? workflowStatusText
								: undefined
						}
						hideHeader={
									hideActivityHeader || !isPrimaryRail
								}
								expanded={railExpanded}
								onToggle={onRailToggle}
								inlineAgentTasks={
									segTasks && segTasks.length > 0
										? segTasks
										: undefined
								}
								agentIndexBase={agentOffset}
							/>
							{/* 收尾且本轮仍画 activity：Done 下、后续主回复上 */}
							{agentsAtTop &&
							!suppressActivity &&
							agentTasks &&
							segIdx === displayLastActivityIdx ? (
								<AgentDoneBars tasks={agentTasks} />
							) : null}
						</div>
					);
				})}
				{streamingSignal ? (
					<div
						onContextMenu={event => {
							const text = displayProse(
								streamingTextSignal.value || streaming || '',
							);
							if (!text.trim()) {
								return;
							}
							showContextMenu(
								event,
								assistantCopyMenuItems(text),
								'助手回复',
							);
						}}
					>
						<StreamingSignalBody />
					</div>
				) : streaming ? (
					<div
						onContextMenu={event => {
							const text = displayProse(streaming);
							if (!text.trim()) {
								return;
							}
							showContextMenu(
								event,
								assistantCopyMenuItems(text),
								'助手回复',
							);
						}}
					>
						<StreamingBody text={streaming} />
					</div>
				) : null}

				{showFilesChanged ? <FilesChanged files={changedFiles} /> : null}
			</div>
		</div>
	);
}

function turnEqual(prev: Props, next: Props): boolean {
	if (prev.turnId !== next.turnId || prev.active !== next.active) {
		return false;
	}
	if (prev.roundSettled !== next.roundSettled) {
		return false;
	}
	if (prev.suppressActivity !== next.suppressActivity) {
		return false;
	}
	if (prev.visibleProseIds !== next.visibleProseIds) {
		return false;
	}
	if (prev.thoughtStartedAt !== next.thoughtStartedAt) {
		return false;
	}
	if (prev.workflowStatusText !== next.workflowStatusText) {
		return false;
	}
	if (prev.isLatestTurn !== next.isLatestTurn) {
		return false;
	}
	if (prev.hideActivityHeader !== next.hideActivityHeader) {
		return false;
	}
	if (
		prev.streaming !== next.streaming ||
		prev.thinking !== next.thinking ||
		prev.streamingSignal !== next.streamingSignal
	) {
		return false;
	}
	if (!multiAgentTaskViewsEqual(prev.agentTasks, next.agentTasks)) {
		return false;
	}
	if (prev.items === next.items) {
		return true;
	}
	return snapshotMatchesItems(snapshotTurnItems(prev.items), next.items);
}

export const AssistantTurn = memo(AssistantTurnInner, turnEqual);
