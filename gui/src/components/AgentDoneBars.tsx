import {memo, useEffect, useRef, useState} from 'react';
import type {MultiAgentTaskView} from '@/lib/api';
import {useChatStore} from '@/stores/chatStore';
import {cn} from '@/lib/utils';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import {ThoughtTicker} from './activity/MorphVerb';

/** 可扫视短名：序号 + 任务描述首段，避免千篇一律的 "Agent"。 */
export function agentDisplayName(desc: string, index: number): string {
	const n = index + 1;
	const raw = (desc || '').replace(/\s+/g, ' ').trim();
	if (!raw) {
		return `子任务 ${n}`;
	}
	const head =
		raw.split(/[，。；：、,.!?\n（(\[【]/u)[0]?.trim() || raw;
	const stripped = head.replace(/^(请|帮我|需要|负责|任务)\s*[:：]?\s*/u, '');
	const base = (stripped || head).trim() || raw;
	const chars = Array.from(base);
	const short =
		chars.length <= 8 ? base : `${chars.slice(0, 8).join('')}…`;
	return `${n}·${short}`;
}

/** token 紧凑显示：万 / k 两档，其余原值。 */
export function formatTokensUsed(n: number): string {
	if (n >= 10_000) {
		return `${(n / 10_000).toFixed(1)}万 tok`;
	}
	if (n >= 1000) {
		return `${(n / 1000).toFixed(1)}k tok`;
	}
	return `${n} tok`;
}

/**
 * 子 Agent 栏：左侧短名可分辨；进行中滚动；完成后显示文字输出（冻结点子 8）。
 * 运行中可取消；失败后可重试；点击主体进入侧链回放。
 */
export const AgentDoneBars = memo(function AgentDoneBars({
	tasks,
	indexBase = 0,
}: {
	tasks: MultiAgentTaskView[];
	/** 全局序号起点（串行分段挂载时避免每段都显示 1·） */
	indexBase?: number;
}) {
	const openAgentView = useChatStore(s => s.openAgentView);
	const cancelAgentTask = useChatStore(s => s.cancelAgentTask);
	const retryAgentTask = useChatStore(s => s.retryAgentTask);
	const activeId = useChatStore(s => s.activeId);
	const liveById = useChatStore(s => s.liveAgentTextById);

	if (tasks.length === 0) {
		return null;
	}

	return (
		<div
			className="xy-agent-done-list"
			role="list"
			aria-label="子 Agent 任务"
		>
			{tasks.map((task, index) => (
				<AgentBar
					key={task.uid}
					task={task}
					index={indexBase + index}
					liveText={
						activeId && task.agentId
							? (liveById[`${activeId}::${task.agentId}`] ?? '')
							: ''
					}
					onOpen={() => {
						if (task.agentId) {
							openAgentView(task.agentId);
						}
					}}
					onCancel={() => {
						if (activeId && task.agentId) {
							void cancelAgentTask(activeId, task.agentId);
						}
					}}
					onRetry={() => {
						if (activeId && task.agentId) {
							void retryAgentTask(activeId, task.agentId);
						}
					}}
				/>
			))}
		</div>
	);
});

const AgentBar = memo(function AgentBar({
	task,
	index,
	liveText,
	onOpen,
	onCancel,
	onRetry,
}: {
	task: MultiAgentTaskView;
	index: number;
	liveText: string;
	onOpen: () => void;
	onCancel: () => void;
	onRetry: () => void;
}) {
	const running = task.status === 'running';
	const pending = task.status === 'pending';
	const failed = task.status === 'failed';
	const done = task.status === 'done';
	const clickable = Boolean(task.agentId);
	const taskName = task.desc?.trim() || `子任务 ${index + 1}`;
	const label = agentDisplayName(task.desc, index);
	const liveTrim = liveText.trim();
	const lastLiveRef = useRef('');
	if (running && liveTrim) {
		const oneLine = liveTrim.replace(/\s+/g, ' ').trim();
		lastLiveRef.current =
			oneLine.length > 42 ? `${Array.from(oneLine).slice(0, 42).join('')}…` : oneLine;
	}
	const tickerSource = (() => {
		const raw = (liveTrim || taskName || 'Working…').replace(/\s+/g, ' ').trim();
		return raw.length > 96 ? `${Array.from(raw).slice(-96).join('')}` : raw;
	})();

	return (
		<div
			role="listitem"
			className={cn(
				'xy-agent-bar',
				failed && 'is-failed',
				running && 'is-running',
				pending && 'is-pending',
				done && 'is-done',
				!clickable && !running && !pending && 'is-disabled',
			)}
		>
			<button
				type="button"
				className="xy-agent-bar-main"
				aria-label={taskName}
				disabled={!clickable && !running && !pending}
				onClick={() => {
					if (clickable) {
						onOpen();
					}
				}}
			>
				<span className="xy-agent-bar-pulse" aria-hidden>
					{running ? (
						<span className="xy-run-dot is-running" />
					) : pending ? (
						<span className="xy-run-dot is-pending" />
					) : done ? (
						<span className="xy-run-dot is-done" />
					) : failed ? (
						<span className="xy-run-dot is-failed-static" />
					) : (
						<span className="xy-agent-bar-caret">▸</span>
					)}
				</span>
			<span
				className={cn('xy-agent-bar-label', failed && 'is-failed')}
				title={taskName}
			>
				{label}
			</span>
			{task.readOnly ? (
				<span
					className="xy-agent-bar-scope is-readonly"
					title="未声明写路径：子 Agent 无法 Write/Edit"
				>
					只读
				</span>
			) : task.scope && task.scope.length > 0 ? (
				<span
					className="xy-agent-bar-scope"
					title={task.scope.join('\n')}
				>
					可写
				</span>
			) : null}
			{task.inboxCount ? (
				<span
					className="xy-agent-bar-inbox rounded px-1 text-[10px] leading-tight text-amber-300"
					style={{background: 'rgba(251,191,36,.12)'}}
					title={`${task.inboxCount} 条 follow-up 已排队（回合结束后自动续跑）`}
				>
					+{task.inboxCount}
				</span>
			) : null}
			{task.tokensUsed ? (
				<span
					className="xy-agent-bar-tokens"
					title={
						task.costCny
							? `共消耗 ${task.tokensUsed.toLocaleString()} tokens，约 ¥${task.costCny.toFixed(4)}`
							: `共消耗 ${task.tokensUsed.toLocaleString()} tokens`
					}
				>
					{formatTokensUsed(task.tokensUsed)}
				</span>
			) : null}
			<span className="xy-agent-bar-out">
					{running ? (
						<ThoughtTicker content={tickerSource} running />
					) : pending ? (
						<span className="xy-agent-bar-pending">排队中</span>
					) : (
						<AgentSettledLabel
							taskName={taskName}
							outputText={
								(failed
									? task.reason || task.result
									: task.result
								)?.trim() || ''
							}
							fromLive={lastLiveRef.current}
						/>
					)}
				</span>
			</button>
			{(running || failed) && task.agentId ? (
				<span className="xy-agent-bar-actions">
					{running ? (
						<button
							type="button"
							className="xy-agent-bar-action"
							aria-label={`取消 ${taskName}`}
							onClick={e => {
								e.stopPropagation();
								onCancel();
							}}
						>
							取消
						</button>
					) : null}
					{failed ? (
						<button
							type="button"
							className="xy-agent-bar-action"
							aria-label={`重试 ${taskName}`}
							onClick={e => {
								e.stopPropagation();
								onRetry();
							}}
						>
							重试
						</button>
					) : null}
				</span>
			) : null}
		</div>
	);
});

/** 完成时：优先文字输出；无 output 时回退任务名。短 live → output/名 morph。 */
function AgentSettledLabel({
	taskName,
	outputText,
	fromLive,
}: {
	taskName: string;
	outputText: string;
	fromLive: string;
}) {
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const oneLine = outputText.replace(/\s+/g, ' ').trim();
	const settled =
		oneLine.length > 0
			? oneLine.length <= 96
				? oneLine
				: `${Array.from(oneLine).slice(0, 96).join('')}…`
			: taskName;
	const liveSnap = fromLive.trim().replace(/\s+/g, ' ');
	const morphOk =
		liveSnap.length > 0 &&
		liveSnap.length <= 48 &&
		!liveSnap.includes('**') &&
		liveSnap !== settled;
	const canMorph = Boolean(smoothness && morphOk);
	const [showSettled, setShowSettled] = useState(!canMorph);

	useEffect(() => {
		if (!canMorph) {
			setShowSettled(true);
			return;
		}
		setShowSettled(false);
		const t = window.setTimeout(() => setShowSettled(true), 40);
		return () => window.clearTimeout(t);
	}, [settled, canMorph]);

	if (!canMorph) {
		return (
			<span className="xy-agent-bar-settled" title={oneLine || taskName}>
				{settled}
			</span>
		);
	}

	return (
		<span className="xy-agent-bar-morph" title={oneLine || taskName}>
			<span className={cn('xy-agent-bar-face', showSettled ? 'off' : 'on')}>
				{liveSnap}
			</span>
			<span className={cn('xy-agent-bar-face', showSettled ? 'on' : 'off')}>
				{settled}
			</span>
		</span>
	);
}
