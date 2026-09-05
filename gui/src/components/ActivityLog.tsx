import {
	memo,
	useCallback,
	useEffect,
	useLayoutEffect,
	useRef,
	useState,
} from 'react';
import type {ActivityStep, DiffStat} from '@/lib/toolActivity';
import {
	extractDiffFence,
	findHandoffStepId,
	formatCollapsedSegmentLabel,
} from '@/lib/toolActivity';
import {parseJsonValue} from '@/lib/safeJson';
import {useHeartbeat} from '@/lib/heartbeat';
import {toolStepMenuItems} from '@/lib/contextMenus';
import {cn} from '@/lib/utils';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';
import type {MultiAgentTaskView} from '@/lib/api';
import {showContextMenu} from '@/components/ui/ContextMenu';
import {MorphVerb, ThoughtTicker} from './activity/MorphVerb';
import {SplitChevron} from './activity/SplitChevron';
import {useExpandReveal} from './activity/useExpandReveal';
import {ExpandPanel} from './activity/ExpandPanel';
import {DiffPreview} from './DiffPreview';
import {AgentDoneBars} from './AgentDoneBars';
import {planAgentCardMounts} from '@/lib/agentCardLayout';

/** 用户展开步骤前不挂载巨大的 tool payload。 */
const RESULT_PREVIEW_CHARS = 4_000;

function DiffBadge({diff}: {diff: DiffStat}) {
	if (diff.add <= 0 && diff.del <= 0) {
		return null;
	}
	return (
		<span className="ml-1.5 inline-flex gap-1 font-mono text-[12px] tabular-nums">
			{diff.add > 0 ? <span className="text-ok">+{diff.add}</span> : null}
			{diff.del > 0 ? (
				<span className="text-danger">-{diff.del}</span>
			) : null}
		</span>
	);
}

const DiffBadgeMemo = memo(DiffBadge);

function formatArgs(raw?: unknown): string {
	if (raw == null) {
		return '—';
	}
	if (typeof raw === 'object') {
		try {
			return JSON.stringify(raw, null, 2);
		} catch {
			return String(raw);
		}
	}
	const text = String(raw).trim();
	if (!text) {
		return '—';
	}
	const parsed = parseJsonValue(text);
	if (parsed != null) {
		try {
			return JSON.stringify(parsed, null, 2);
		} catch {
			return text;
		}
	}
	return text;
}

const RUNTIME_TAIL_RE =
	/^(No matches\.|No matches found|No files found|Tip:|\(Results are truncated|\[提示\]|\(archived;|你正在用完全相同的参数)/;

function sanitizePreviewLines(out: string): string[] {
	return out
		.split('\n')
		.map(line => line.trim())
		.filter(line => line.length > 0 && !RUNTIME_TAIL_RE.test(line));
}

export function oneLinePreview(step: ActivityStep): string {
	const fileVerbs = new Set([
		'Created',
		'Creating',
		'Wrote',
		'Writing',
		'Edited',
		'Editing',
		'Failed',
		'Read',
		'Reading',
	]);
	if (fileVerbs.has(step.verb) && step.detail.trim()) {
		return step.detail;
	}
	if (
		(step.verb === 'Updating' ||
			step.verb === 'Checked' ||
			step.verb === 'Thought') &&
		step.detail.trim()
	) {
		return step.detail;
	}
	if (step.running && !step.result?.trim()) {
		return step.detail || 'Running…';
	}
	if (step.detail.trim()) {
		return step.detail.length > 80
			? `${step.detail.slice(0, 80)}…`
			: step.detail;
	}
	const lines = sanitizePreviewLines(step.result ?? '');
	if (lines.length > 0) {
		const first = lines[0];
		if (!first) {
			const rawFirst =
				(step.result ?? '').split('\n').at(0)?.trim() || '';
			return rawFirst.length > 80
				? `${rawFirst.slice(0, 80)}…`
				: rawFirst;
		}
		return first.length > 80 ? `${first.slice(0, 80)}…` : first;
	}
	return '';
}

function StepDetailBody({
	args,
	result,
	running,
	verb,
}: {
	args?: string;
	result?: string;
	running?: boolean;
	verb?: string;
}) {
	const [full, setFull] = useState(false);
	const stdout = result?.trim() ?? '';
	const diff = stdout ? extractDiffFence(stdout) : undefined;
	const fileVerb = Boolean(
		verb &&
			[
				'Created',
				'Creating',
				'Wrote',
				'Writing',
				'Edited',
				'Editing',
				'Failed',
			].includes(verb),
	);

	if (fileVerb && diff) {
		return (
			<div className="mt-1 space-y-2 pl-1">
				<DiffPreview diff={diff} />
			</div>
		);
	}

	const large = stdout.length > RESULT_PREVIEW_CHARS;
	const text =
		!full && large ? `${stdout.slice(0, RESULT_PREVIEW_CHARS)}\n…` : stdout;

	return (
		<div className="mt-1 space-y-2 pl-1">
			<section>
				<h4 className="mb-0.5 font-mono text-[10px] tracking-wide text-mute uppercase">
					Args
				</h4>
				<pre className="whitespace-pre-wrap break-all rounded bg-glass-soft/50 px-2 py-1.5 font-mono text-[11px] leading-relaxed text-mute">
					{formatArgs(args)}
				</pre>
			</section>
			<section>
				<h4 className="mb-0.5 font-mono text-[10px] tracking-wide text-mute uppercase">
					Output
				</h4>
				{stdout ? (
					<>
						<pre className="whitespace-pre-wrap break-all rounded bg-glass-soft/50 px-2 py-1.5 font-mono text-[11px] leading-relaxed text-mute">
							{text}
						</pre>
						{large && !full ? (
							<button
								type="button"
								onClick={() => setFull(true)}
								className="mt-0.5 text-[11px] text-accent hover:text-accent-hover"
							>
								显示全部（{stdout.length.toLocaleString()} 字符）
							</button>
						) : null}
					</>
				) : (
					<pre className="rounded bg-glass-soft/50 px-2 py-1.5 font-mono text-[11px] text-mute">
						{running ? 'Running…' : '—'}
					</pre>
				)}
			</section>
		</div>
	);
}

type StepRowProps = {
	step: ActivityStep;
	handoff?: boolean;
	appear?: boolean;
	collapsing?: boolean;
	onThoughtToken?: (token: string) => void;
};

function stepRowEqual(a: StepRowProps, b: StepRowProps): boolean {
	const x = a.step;
	const y = b.step;
	return (
		x.id === y.id &&
		x.verb === y.verb &&
		x.detail === y.detail &&
		x.error === y.error &&
		x.running === y.running &&
		x.agent === y.agent &&
		(x.args?.length ?? 0) === (y.args?.length ?? 0) &&
		(x.result?.length ?? 0) === (y.result?.length ?? 0) &&
		(x.thoughtContent?.length ?? 0) === (y.thoughtContent?.length ?? 0) &&
		x.thoughtContent === y.thoughtContent &&
		x.diff?.add === y.diff?.add &&
		x.diff?.del === y.diff?.del &&
		a.handoff === b.handoff &&
		a.appear === b.appear &&
		a.collapsing === b.collapsing
	);
}

function thoughtPeekSnippet(content: string): string {
	const one = content.replace(/\s+/g, ' ').trim();
	if (!one) {
		return '';
	}
	if (one.length <= 140) {
		return one;
	}
	const parts = one.split(/(?<=[。！？.!?\n])\s*/u).filter(Boolean);
	const last = parts.at(-1) || one;
	if (last.length <= 140) {
		return last;
	}
	return `…${one.slice(-120)}`;
}

function ThoughtStepRow({
	step,
	collapsing,
	onThoughtToken,
}: StepRowProps) {
	const content = step.thoughtContent?.trim() || '';
	const running = Boolean(step.running);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const {open, mounted, toggle} = useExpandReveal();
	const preview =
		content.replace(/\s+/g, ' ').slice(0, 72) ||
		(step.detail === 'briefly' ? 'briefly' : step.detail) ||
		'—';
	const previewEllipsis =
		content.replace(/\s+/g, ' ').length > 72 ? `${preview}…` : preview;
	const peek = !running && !open && content ? thoughtPeekSnippet(content) : '';

	const onToggle = () => {
		if (!content || running) {
			return;
		}
		toggle();
	};

	return (
		<div
			className={cn(
				'xy-split-step thought-step',
				running && 'is-running',
				Boolean(peek) && smoothness && 'group/thought',
			)}
		>
			<button
				type="button"
				className="xy-split-left"
				aria-expanded={running ? true : open}
				disabled={running || !content}
				onClick={onToggle}
			>
				{/* 进行中用 Thinking；收束后 A8 翻到 Thought（禁止连转） */}
				<MorphVerb verb={running ? 'Thinking' : 'Thought'} />
			</button>
			<div className="xy-split-right group/step relative min-w-0">
				{running ? (
					content ? (
						<ThoughtTicker
							content={content}
							running
							collapsing={collapsing}
							onToken={onThoughtToken}
						/>
					) : (
						<span className="xy-thought-ticker" aria-hidden>
							<span className="xy-thought-blink" />
						</span>
					)
				) : (
					<>
						<button
							type="button"
							disabled={!content}
							onClick={onToggle}
							className="xy-split-row-main"
						>
							<span
								className={cn(
									'xy-split-preview',
									open && 'text-mute',
								)}
								title={content || undefined}
							>
								{open ? step.detail || 'Thought' : previewEllipsis}
							</span>
							<SplitChevron open={open} />
						</button>
						{peek && smoothness ? (
							<div className="xy-thought-peek" role="tooltip">
								{peek}
							</div>
						) : null}
						{mounted ? (
							<ExpandPanel open={open} innerClassName="xy-tool-step-body">
								{content ? (
									<button
										type="button"
										className="xy-thought-expand-body"
										onClick={onToggle}
									>
										{content}
									</button>
								) : null}
							</ExpandPanel>
						) : null}
					</>
				)}
			</div>
		</div>
	);
}

function ToolStepRow({
	step,
	handoff,
	appear,
}: {
	step: ActivityStep;
	handoff?: boolean;
	/** 新工具入轨：延迟后再过渡显现 */
	appear?: boolean;
}) {
	const {open, mounted, toggle} = useExpandReveal();
	const preview = oneLinePreview(step);

	return (
		<div
			className={cn(
				'xy-split-step',
				step.error && 'is-failed',
				step.verb === 'Edited' && !step.error && 'is-ok',
				handoff && 'is-handoff',
				appear && 'is-tool-appear',
			)}
			onContextMenu={event => {
				showContextMenu(
					event,
					toolStepMenuItems({
						preview,
						detail: step.detail,
						result: step.result,
					}),
					'工具步骤',
				);
			}}
		>
			<button
				type="button"
				onClick={toggle}
				aria-expanded={open}
				className="xy-split-left"
			>
				{/* 动词态由 toolToStep 给出；settle 时 Editing→Edited 走 A8，不连转 */}
				<MorphVerb
					verb={step.verb}
					error={Boolean(step.error) || step.verb === 'Failed'}
				/>
			</button>
			<div className="xy-split-right group/step min-w-0">
				<button
					type="button"
					onClick={toggle}
					className="xy-split-row-main"
				>
					<span className="xy-split-preview" title={preview}>
						{preview}
					</span>
					{step.diff ? <DiffBadgeMemo diff={step.diff} /> : null}
					<SplitChevron open={open} />
				</button>
				{mounted ? (
					<ExpandPanel open={open} innerClassName="xy-tool-step-body">
						<StepDetailBody
							args={step.args}
							result={step.result}
							running={step.running}
							verb={step.verb}
						/>
					</ExpandPanel>
				) : null}
			</div>
		</div>
	);
}

function StepRowInner({
	step,
	handoff,
	appear,
	collapsing,
	onThoughtToken,
}: StepRowProps) {
	if (step.verb === 'Thought') {
		return (
			<ThoughtStepRow
				step={step}
				collapsing={collapsing}
				onThoughtToken={onThoughtToken}
			/>
		);
	}
	return <ToolStepRow step={step} handoff={handoff} appear={appear} />;
}

const StepRow = memo(StepRowInner, stepRowEqual);

function formatElapsed(ms: number): string {
	const s = Math.floor(ms / 1000);
	const m = Math.floor(s / 60);
	const r = s % 60;
	return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

type Props = {
	summary: string;
	diffs: DiffStat;
	steps: ActivityStep[];
	expanded: boolean;
	onToggle: () => void;
	active?: boolean;
	/** A7：进行中起点（缺省为挂载时刻） */
	startedAt?: number | null;
	/** done 展开层：只画步骤轨，无 Working / N steps 顶栏 */
	hideHeader?: boolean;
	/**
	 * 进行中：在 Delegating/Delegated/Failed(Agent) 步骤后就近插入子 Agent 卡片。
	 * 结束后由 AssistantTurn 提到 Done 下、主回复上，此处勿传。
	 */
	inlineAgentTasks?: MultiAgentTaskView[];
	/** 本段任务全局序号起点（跨段串行时 2·/3· 正确） */
	agentIndexBase?: number;
};

function agentTasksFingerprint(tasks: MultiAgentTaskView[] | undefined): string {
	if (!tasks?.length) {
		return '';
	}
	let out = '';
	for (const t of tasks) {
		out += `${t.uid}:${t.status}:${t.desc.length};`;
	}
	return out;
}

function activityEqual(prev: Props, next: Props): boolean {
	if (
		prev.summary !== next.summary ||
		prev.expanded !== next.expanded ||
		prev.active !== next.active ||
		prev.startedAt !== next.startedAt ||
		prev.hideHeader !== next.hideHeader ||
		prev.agentIndexBase !== next.agentIndexBase ||
		prev.diffs.add !== next.diffs.add ||
		prev.diffs.del !== next.diffs.del ||
		prev.steps.length !== next.steps.length ||
		agentTasksFingerprint(prev.inlineAgentTasks) !==
			agentTasksFingerprint(next.inlineAgentTasks)
	) {
		return false;
	}
	for (let i = 0; i < prev.steps.length; i += 1) {
		if (
			!stepRowEqual(
				{step: prev.steps[i]!},
				{step: next.steps[i]!},
			)
		) {
			return false;
		}
	}
	return true;
}

/** #10 Split header + A7/A8 + L10 activity。 */
function ActivityLogInner({
	summary,
	diffs,
	steps,
	expanded,
	onToggle,
	active,
	startedAt = null,
	hideHeader = false,
	inlineAgentTasks,
	agentIndexBase = 0,
}: Props) {
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const showDiff = diffs.add > 0 || diffs.del > 0 ? diffs : undefined;
	const lastRunningIdx = (() => {
		for (let i = steps.length - 1; i >= 0; i -= 1) {
			if (steps[i]?.running) {
				return i;
			}
		}
		return -1;
	})();
	const anyRunning =
		lastRunningIdx >= 0 && steps[lastRunningIdx]?.running === true;

	const [elapsed, setElapsed] = useState(0);
	const startRef = useRef<number>(startedAt ?? Date.now());
	useEffect(() => {
		if (startedAt != null) {
			startRef.current = startedAt;
		}
	}, [startedAt]);

	const working = Boolean(active || anyRunning);

	const tickElapsed = useCallback(
		() => setElapsed(Date.now() - startRef.current),
		[],
	);
	useEffect(() => {
		if (working) {
			tickElapsed();
		}
	}, [working, tickElapsed]);
	// 全局 1s 心跳:共享单一定时器,替代自建 setInterval(见 lib/heartbeat.ts)
	useHeartbeat(tickElapsed, working);

	// 点子 3：Working → 折叠时 Thought 先淡出
	const [collapsing, setCollapsing] = useState(false);
	const prevWorking = useRef(working);
	useEffect(() => {
		const was = prevWorking.current;
		prevWorking.current = working;
		if (was && !working && smoothness) {
			setCollapsing(true);
			const t = window.setTimeout(() => setCollapsing(false), 480);
			return () => window.clearTimeout(t);
		}
		setCollapsing(false);
	}, [working, smoothness]);

	// H2：新步骤先隐身占位，延迟后再淡入；Thought 先于同批工具，避免视觉乱序
	const [handoffId, setHandoffId] = useState<string | null>(null);
	const [appearIds, setAppearIds] = useState<ReadonlySet<string>>(
		() => new Set(),
	);
	const handoffTimer = useRef<number | null>(null);
	const appearClearTimers = useRef<Map<string, number>>(new Map());
	const seenStepIds = useRef<Set<string>>(new Set());

	useEffect(() => {
		return () => {
			if (handoffTimer.current != null) {
				window.clearTimeout(handoffTimer.current);
			}
			for (const t of appearClearTimers.current.values()) {
				window.clearTimeout(t);
			}
			appearClearTimers.current.clear();
		};
	}, []);

	useLayoutEffect(() => {
		const known = seenStepIds.current;
		const freshTools = steps.filter(
			s => s.verb !== 'Thought' && !known.has(s.id),
		);
		for (const s of steps) {
			known.add(s.id);
		}
		// Thought/Thinking 立即显示，不参与延迟淡入（否则会先隐身再消失）
		if (!smoothness || !working || freshTools.length === 0) {
			return;
		}
		const ids = freshTools.map(s => s.id);
		const handoffTarget = freshTools[freshTools.length - 1]!;
		setAppearIds(prevAppear => {
			const next = new Set(prevAppear);
			for (const id of ids) {
				next.add(id);
			}
			return next;
		});
		// H2：下一工具入轨时动词柔闪（不限 path 命中）
		if (handoffTimer.current != null) {
			window.clearTimeout(handoffTimer.current);
		}
		handoffTimer.current = window.setTimeout(() => {
			setHandoffId(handoffTarget.id);
			handoffTimer.current = window.setTimeout(() => {
				setHandoffId(null);
				handoffTimer.current = null;
			}, 700);
		}, 160);

		const holdMs = 160 + 520;
		for (const id of ids) {
			const prevT = appearClearTimers.current.get(id);
			if (prevT != null) {
				window.clearTimeout(prevT);
			}
			const t = window.setTimeout(() => {
				appearClearTimers.current.delete(id);
				setAppearIds(prevAppear => {
					if (!prevAppear.has(id)) {
						return prevAppear;
					}
					const next = new Set(prevAppear);
					next.delete(id);
					return next;
				});
			}, holdMs);
			appearClearTimers.current.set(id, t);
		}
	}, [steps, working, smoothness]);

	const onThoughtToken = useCallback(
		(token: string) => {
			if (!smoothness) {
				return;
			}
			const id = findHandoffStepId(token, steps);
			if (!id || appearIds.has(id)) {
				return;
			}
			if (handoffTimer.current != null) {
				window.clearTimeout(handoffTimer.current);
			}
			setHandoffId(id);
			handoffTimer.current = window.setTimeout(() => {
				setHandoffId(null);
				handoffTimer.current = null;
			}, 780);
		},
		[steps, smoothness, appearIds],
	);

	const resolveStep = (s: ActivityStep, index: number): ActivityStep => {
		const live = Boolean(s.running && index === lastRunningIdx);
		return live === s.running ? s : {...s, running: live};
	};

	/** 折叠行：Thought 4s / N steps；进行中 Working + 计时 */
	const collapsedLabel = formatCollapsedSegmentLabel(steps, summary);

	const cardByStep = new Map<
		number,
		{tasks: MultiAgentTaskView[]; indexBase: number}
	>();
	if (inlineAgentTasks && inlineAgentTasks.length > 0) {
		for (const m of planAgentCardMounts(steps, inlineAgentTasks.length)) {
			cardByStep.set(m.afterStepIndex, {
				tasks: inlineAgentTasks.slice(m.taskStart, m.taskEnd),
				indexBase: agentIndexBase + m.taskStart,
			});
		}
	}

	const rail = (
		<div className="xy-split-rail">
			{steps.map((s, i) => {
				const mount = cardByStep.get(i);
				return (
					<div key={s.id} className="space-y-2">
						<StepRow
							step={resolveStep(s, i)}
							handoff={handoffId === s.id}
							appear={appearIds.has(s.id)}
							collapsing={collapsing && s.verb === 'Thought'}
							onThoughtToken={
								s.verb === 'Thought' ? onThoughtToken : undefined
							}
						/>
						{mount ? (
							<AgentDoneBars
								tasks={mount.tasks}
								indexBase={mount.indexBase}
							/>
						) : null}
					</div>
				);
			})}
		</div>
	);

	if (hideHeader) {
		return (
			<div className="xy-activity-split select-none" data-headless="">
				<ExpandPanel
					open={expanded}
					innerClassName="xy-activity-detail-inner"
				>
					{rail}
				</ExpandPanel>
			</div>
		);
	}

	return (
		<div className="xy-activity-split select-none">
			<button
				type="button"
				onClick={onToggle}
				className="xy-split-head group/head"
				aria-expanded={expanded}
				title="投影视图：展示引擎当前投影的活动摘要，非完整 transcript；审计明细见 /v1/audit"
			>
				{working ? (
					<>
						<span className="xy-split-head-lead">
							<span className="xy-split-head-label">Working</span>
							<SplitChevron open={expanded} />
						</span>
						<span className="xy-split-head-meta xy-activity-timer">
							{formatElapsed(elapsed)}
						</span>
					</>
				) : (
					<>
						<span className="xy-split-head-lead">
							<span className="xy-split-head-label xy-split-summary">
								{collapsedLabel}
							</span>
							<SplitChevron open={expanded} />
						</span>
						<span className="xy-split-head-meta">
							{showDiff ? (
								<span className="xy-done-extra">
									<span className="text-ok">+{showDiff.add}</span>
									<span className="text-danger">
										-{showDiff.del}
									</span>
								</span>
							) : null}
						</span>
					</>
				)}
			</button>

			<ExpandPanel
				open={expanded}
				innerClassName="xy-activity-detail-inner"
			>
				{rail}
			</ExpandPanel>
		</div>
	);
}

export const ActivityLog = memo(ActivityLogInner, activityEqual);
