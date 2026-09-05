/**
 * SessionJobsBadge.tsx — 42 号 P0 GUI：后台任务触发器 + 角标 + 只读弹层。
 *
 * 对齐 dsh-client-ui-jobs（42 号 §8）：
 * - 角标 = running+stopping 计数，**为零整个隐藏**（会话无任务不长控件）。
 * - 弹层行 = kind / label / detail（有则取代状态词）/ 状态标记 / 耗时——
 *   活跃行每秒推进、终态在 finishedAt 冻结；终态行弱化保留。
 * - 排序确定性：活跃行前（startedAt 升序）、终态行后（finishedAt 降序）。
 * - 数据：SSE jobs 帧（turn 起点播种，经 chatStore onJobs 落库）+ GET 轻量
 *   轮询（有任务才轮询；owner turn 结束后的结算变化靠它补齐）。
 * - 只读纪律：无流直读、无人类中断行（冻结口径 6）。
 */
import {useEffect, useRef, useState} from 'react';
import {Loader2, ListTree} from 'lucide-react';
import {useChatStore} from '@/stores/chatStore';
import {cn} from '@/lib/utils';
import {
	activeJobsCount,
	fetchSessionJobs,
	sortJobsForPanel,
	type JobSnapshot,
} from '@/lib/api/jobs';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';

const JOBS_POLL_MS = 5000;

function formatElapsed(ms: number): string {
	const total = Math.max(0, Math.floor(ms / 1000));
	const h = Math.floor(total / 3600);
	const m = Math.floor((total % 3600) / 60);
	const s = total % 60;
	const mm = String(m).padStart(2, '0');
	const ss = String(s).padStart(2, '0');
	return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** whole-value 写回 store（SSE 帧与 GET 共用同形；空集 = 删除键）。 */
function writeJobs(sessionId: string, jobs: JobSnapshot[]) {
	useChatStore.setState(s => {
		const next = {...s.sessionJobsById};
		if (jobs.length === 0) {
			delete next[sessionId];
		} else {
			next[sessionId] = jobs;
		}
		return {sessionJobsById: next};
	});
}

/**
 * 42 号 P0 轻量轮询：有任务的会话每 5s GET 快照并 whole-value 覆写；
 * 无任务只做一次会话切换播种。不可见 / 在途时跳过，绝不阻塞 UI。
 */
export function useSessionJobsLive(sessionId: string | null) {
	const inflight = useRef(false);
	useEffect(() => {
		if (!sessionId) return;
		let stopped = false;
		const refresh = async () => {
			if (inflight.current || document.visibilityState !== 'visible') {
				return;
			}
			inflight.current = true;
			try {
				const {jobs} = await fetchSessionJobs(sessionId);
				if (!stopped) {
					writeJobs(sessionId, jobs);
				}
			} catch {
				/* 降级：下个周期再试 */
			} finally {
				inflight.current = false;
			}
		};
		void refresh();
		// 仅在有任务时持续轮询（检查 store，而不是闭包快照）。
		const timer = window.setInterval(() => {
			const cur = useChatStore.getState().sessionJobsById?.[sessionId];
			if (cur && cur.length > 0) {
				void refresh();
			}
		}, JOBS_POLL_MS);
		return () => {
			stopped = true;
			window.clearInterval(timer);
		};
	}, [sessionId]);
}

const STATUS_TEXT: Record<string, string> = {
	running: '运行中',
	stopping: '停止中',
	succeeded: '已完成',
	failed: '失败',
	killed: '已终止',
};

function statusTone(status: string): string {
	if (status === 'running') return 'text-ok';
	if (status === 'stopping') return 'text-warn';
	if (status === 'failed' || status === 'killed') return 'text-warn';
	return 'text-mute';
}

/** 模块级稳定空集：选择器回退必须引用稳定，否则 useSyncExternalStore 每渲染
 * 误判快照变化 → Maximum update depth（41 号 GoalDock 用 null 回退同理）。 */
const EMPTY_JOBS: JobSnapshot[] = [];

export function SessionJobsBadge({
	sessionId,
	mode = 'main',
}: {
	sessionId: string | null;
	mode?: 'main' | 'side';
}) {
	// 订阅整个 map（store 不变时引用稳定），键缺失回退模块级常量。
	const jobsRecord = useChatStore(s => s.sessionJobsById);
	const jobs = sessionId ? (jobsRecord[sessionId] ?? EMPTY_JOBS) : EMPTY_JOBS;
	const [open, setOpen] = useState(false);
	const rootRef = useRef<HTMLDivElement>(null);
	useSessionJobsLive(sessionId);

	// 活跃行存在时每秒推进耗时（时钟只在有活物且弹层打开时运行）。
	const [, forceTick] = useState(0);
	const hasActive = jobs.some(
		j => j.status === 'running' || j.status === 'stopping',
	);
	useEffect(() => {
		if (!open || !hasActive) return;
		const t = window.setInterval(() => forceTick(n => n + 1), 1000);
		return () => window.clearInterval(t);
	}, [open, hasActive]);

	useEffect(() => {
		if (!open) return;
		const onDocumentMouseDown = (event: MouseEvent) => {
			if (!rootRef.current?.contains(event.target as Node)) {
				setOpen(false);
			}
		};
		pushEscLayer('jobs-popover', () => setOpen(false));
		document.addEventListener('mousedown', onDocumentMouseDown);
		return () => {
			document.removeEventListener('mousedown', onDocumentMouseDown);
			popEscLayer('jobs-popover');
		};
	}, [open]);

	useEffect(() => {
		setOpen(false);
	}, [sessionId, mode]);

	const active = activeJobsCount(jobs);
	if (!sessionId || jobs.length === 0) {
		return null; // 角标为零整个隐藏（42 号 §8）
	}
	const rows = sortJobsForPanel(jobs);
	const now = Date.now();

	return (
		<div ref={rootRef} className="relative shrink-0">
			<button
				type="button"
				aria-label={`后台任务（${active} 个进行中，共 ${jobs.length}）`}
				aria-expanded={open}
				onClick={() => setOpen(o => !o)}
				className={cn(
					'xy-press inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-[10px] transition-colors hover:bg-glass-hover',
					open ? 'bg-glass-hover text-ink' : 'text-mute',
				)}
			>
				{hasActive ? (
					<Loader2
						className="size-3 animate-spin text-ok"
						strokeWidth={2}
						aria-hidden
					/>
				) : (
					<ListTree className="size-3" strokeWidth={1.8} aria-hidden />
				)}
				<span>
					{active > 0 ? `后台 ${active}/${jobs.length}` : `后台 ${jobs.length}`}
				</span>
			</button>
			{open ? (
				<div
					role="region"
					aria-label="后台任务"
					className="absolute right-0 top-[calc(100%+6px)] z-[70] max-h-72 w-[min(360px,calc(100vw-32px))] overflow-y-auto rounded-xl border border-frame bg-glass-strong p-1.5 shadow-[var(--xy-modal-shadow)]"
				>
					<p className="px-1.5 pb-1 pt-0.5 text-[10px] text-mute">
						后台任务（只读；完成会自动通知模型，由模型 job_output 收结果）
					</p>
					<ul className="m-0 list-none space-y-0.5 p-0">
						{rows.map(j => {
							const isActive = j.status === 'running' || j.status === 'stopping';
							const elapsed = formatElapsed(
								(isActive ? now : j.finished_at || now) - j.started_at,
							);
							return (
								<li
									key={j.job_id}
									className={cn(
										'rounded-lg border border-line/50 bg-glass-hover/40 px-2 py-1.5',
										!isActive && 'opacity-60',
									)}
								>
									<div className="flex items-center gap-1.5">
										{isActive ? (
											<Loader2
												className="size-3 shrink-0 animate-spin text-ok"
												strokeWidth={2}
												aria-hidden
											/>
										) : (
											<span
												className={cn(
													'size-1.5 shrink-0 rounded-full',
													j.status === 'failed' || j.status === 'killed'
														? 'bg-warn'
														: 'bg-mute/60',
												)}
												aria-hidden
											/>
										)}
										<span className="min-w-0 flex-1 truncate text-[11px] leading-4 text-ink">
											{j.label || j.kind}
										</span>
										<span
											className={cn(
												'shrink-0 font-mono text-[10px]',
												statusTone(j.status),
											)}
										>
											{elapsed}
										</span>
									</div>
									<div className="mt-0.5 flex items-center gap-1.5 text-[10px] leading-4">
										<span className="shrink-0 font-mono text-mute">
											{j.job_id}
										</span>
										{/* detail 有则取代状态词（42 号 §8）。 */}
										<span
											className={cn(
												'min-w-0 flex-1 truncate',
												j.detail ? 'text-ink-soft' : statusTone(j.status),
											)}
										>
											{j.detail || (STATUS_TEXT[j.status] ?? j.status)}
										</span>
									</div>
								</li>
							);
						})}
					</ul>
				</div>
			) : null}
		</div>
	);
}
