import {useEffect, useRef, useState} from 'react';
import {ExternalLink, RefreshCw, Camera} from 'lucide-react';
import {A3NativePanel} from '@/components/A3NativePanel';
import {PageShell} from '@/components/PageShell';
import {
	fetchLiveUsageReport,
	getMemoryReport,
	memoryReportViewUrl,
	runMemorySnapshot,
	type LiveUsageReport,
	type MemoryReportInfo,
} from '@/lib/api';
import {openExternalUrl} from '@/lib/openExternal';
import {toast} from '@/lib/toast';
import {cn} from '@/lib/utils';

/**
 * 用量页容器：主面读**实时账本**，快照降级成次要动作。
 *
 * 原来这一层的主面是 A3 快照报告（`/report/data`，读不出来时贴 10 MB 网页 iframe），
 * 于是"今天"永远是空的，除非点一次「立即快照」。现在：
 *
 * - 主面 = `GET /v1/usage/report`（本机账本实时聚合，见 `usage/live_report.py`）；
 *   读不出就直说读不出 + 给重试，**不再退回 iframe**——用一份可能过期的快照报告
 *   顶掉"读不出"这个事实，是这类界面最坏的兜底。
 * - 快照 = 生成/更新 `docs/A3-monitor.html`（表D 与 schtasks 的证据链，一行没动），
 *   按钮留在页面上但降级；报告存在时可「新窗口」打开。
 * - 两条通路各自的"没有 / 没读到"仍然分家：账本缺文件是正面事实（界面说"还没有用量
 *   记录"），HTTP 失败/形状变了才是没读到。
 */

/** 快照状态行：只在后端**明确**给了 exists 时才说"尚未生成"。 */
function snapshotMeta(report: MemoryReportInfo | null, loading: boolean, error: string): string {
	if (error) return error;
	if (!report) return loading ? '正在读取快照状态…' : '未读到快照状态';
	if (!report.exists) return '尚未生成网页报告（不影响本页数据，本页读的是实时账本）';
	const name = report.path?.split(/[\\/]/).pop() ?? '网页报告';
	const days = report.days?.length ? `${report.days.length} 天` : null;
	return [name, days].filter(Boolean).join(' · ');
}

type Props = {active?: boolean};

export function UsagePageBody({active}: Props) {
	const [report, setReport] = useState<LiveUsageReport | null>(null);
	const [error, setError] = useState('');
	const [loading, setLoading] = useState(false);

	const [snapInfo, setSnapInfo] = useState<MemoryReportInfo | null>(null);
	const [snapLoading, setSnapLoading] = useState(false);
	const [snapError, setSnapError] = useState('');
	const [running, setRunning] = useState(false);
	const [opening, setOpening] = useState(false);
	const [snapshotResult, setSnapshotResult] = useState('');

	const requestRef = useRef(0);
	const snapRequestRef = useRef(0);
	const mountedRef = useRef(true);
	const snapshotInFlightRef = useRef(false);

	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
			requestRef.current += 1;
			snapRequestRef.current += 1;
		};
	}, []);

	const loadLive = async () => {
		const requestId = ++requestRef.current;
		setLoading(true);
		try {
			const r = await fetchLiveUsageReport();
			if (!mountedRef.current || requestRef.current !== requestId) return;
			if (r.ok && r.data) {
				setReport(r.data);
				setError('');
			} else {
				// 读不出不顶假数据：保留上一次成功读数，同时把原因写在界面上。
				setError(`没读到本机用量账本（${r.message || 'unknown'}）`);
			}
		} catch (err) {
			if (mountedRef.current && requestRef.current === requestId) {
				setError(err instanceof Error ? err.message : '读取用量账本失败');
			}
		} finally {
			if (mountedRef.current && requestRef.current === requestId) setLoading(false);
		}
	};

	useEffect(() => {
		if (!active) return;
		void loadLive();
	}, [active]);

	const loadSnapshotStatus = async () => {
		const requestId = ++snapRequestRef.current;
		setSnapLoading(true);
		try {
			const r = await getMemoryReport();
			if (!mountedRef.current || snapRequestRef.current !== requestId) return;
			if (r.ok && r.data) {
				setSnapInfo(r.data);
				setSnapError('');
			} else {
				setSnapInfo(null);
				setSnapError(`未读到快照状态（${r.message || 'unknown'}）`);
			}
		} catch (err) {
			if (mountedRef.current && snapRequestRef.current === requestId) {
				setSnapError(err instanceof Error ? err.message : '读取快照状态失败');
			}
		} finally {
			if (mountedRef.current && snapRequestRef.current === requestId) setSnapLoading(false);
		}
	};

	useEffect(() => {
		if (!active) return;
		void loadSnapshotStatus();
	}, [active]);

	const runSnapshot = async () => {
		if (snapshotInFlightRef.current) return;
		snapshotInFlightRef.current = true;
		setRunning(true);
		setSnapshotResult('');
		try {
			const r = await runMemorySnapshot();
			if (!mountedRef.current) return;
			if (!r.ok || !r.data) {
				// 读不到回执 ≠ 后端没跑：这里只能说"未确认"，不能说"失败"。
				toast.error(`A3 快照未确认：${r.message || 'unknown'}`);
				return;
			}
			const result = r.data;
			if (!result.ok) {
				toast.error(result.error || 'A3 快照失败');
				return;
			}
			const days = result.days ?? (result.day ? [result.day] : []);
			setSnapshotResult(
				days.length > 1
					? `补齐 ${days.length} 天（${days[0]} → ${days[days.length - 1]}）`
					: `已更新 ${result.day ?? '今日'} 快照`,
			);
			if (mountedRef.current) await loadSnapshotStatus();
		} catch (error) {
			if (mountedRef.current) {
				toast.error(error instanceof Error ? error.message : 'A3 快照失败');
			}
		} finally {
			snapshotInFlightRef.current = false;
			if (mountedRef.current) setRunning(false);
		}
	};

	const openReport = async () => {
		setOpening(true);
		try {
			await openExternalUrl(memoryReportViewUrl());
		} catch (error) {
			toast.error(error instanceof Error ? error.message : '打开 A3 报告失败');
		} finally {
			setOpening(false);
		}
	};

	const emptyLedger = report != null && report.days.length === 0;

	return (
		<section className="xy-a3-report xy-usage-section mb-5 overflow-hidden rounded-[var(--xy-radius-pane)] border border-line bg-paper">
			<div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
				<div className="min-w-0">
					<h2 className="flex items-center gap-2 text-[14px] font-medium text-ink">
						用量
						<span className="rounded-full bg-accent-soft px-2 py-0.5 text-[10px] text-accent">
							实时账本
						</span>
					</h2>
					<p className="mt-0.5 text-[11px] text-mute" data-a3-live-status>
						{error ||
							(loading && !report
								? '正在读取本机用量账本…'
								: emptyLedger
									? '本机还没有用量记录：跑一次对话就会开始记账（账本在 ~/.xeyo/usage/）。'
									: report
										? `${report.source.rows == null ? '—' : report.source.rows.toLocaleString('en-US')} 笔用量记录 · 来源 ${report.source.path || '本机账本'}`
										: '未读到用量')}
					</p>
				</div>
				<div className="flex shrink-0 items-center gap-2">
					<button
						type="button"
						disabled={loading}
						onClick={() => void loadLive()}
						aria-label="刷新用量数据"
						className="xy-icon-btn rounded-lg p-2 text-mute hover:bg-glass-hover hover:text-ink disabled:opacity-50"
					>
						<RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
					</button>
					<button
						type="button"
						disabled={running}
						onClick={() => void runSnapshot()}
						title="生成 docs/A3-monitor.html 网页报告（表D 的证据链），本页数据不依赖它"
						className="xy-press inline-flex items-center gap-1.5 rounded-lg border border-line/70 px-3 py-1.5 text-xs text-ink-soft transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-accent disabled:opacity-50"
					>
						<Camera className="h-3.5 w-3.5" aria-hidden />
						{running ? '快照中…' : '生成网页报告'}
					</button>
					<button
						type="button"
						disabled={opening || snapInfo?.exists !== true}
						onClick={() => void openReport()}
						className="xy-press inline-flex items-center gap-1.5 rounded-lg border border-line/70 px-3 py-1.5 text-xs text-ink-soft transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-accent disabled:opacity-50"
					>
						<ExternalLink className="h-3.5 w-3.5" aria-hidden />
						{opening ? '打开中…' : '新窗口'}
					</button>
				</div>
			</div>

			{/* 快照状态降级成一行说明：它只关于那份网页报告，不关于本页数据。 */}
			<div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/60 bg-paper-deep px-4 py-1.5 text-[11px] text-mute">
				<span data-a3-snapshot-status>
					{snapshotResult
						? `网页报告 · ${snapshotResult}`
						: snapshotMeta(snapInfo, snapLoading, snapError)}
				</span>
				<button
					type="button"
					disabled={snapLoading}
					onClick={() => void loadSnapshotStatus()}
					className="xy-press rounded-[var(--xy-radius-control)] px-2 py-0.5 text-[11px] text-ink-soft hover:bg-glass-hover hover:text-ink disabled:opacity-50"
				>
					{snapLoading ? '读取中…' : '重读快照状态'}
				</button>
			</div>

			{report ? <A3NativePanel data={report} /> : null}

			{!report && !loading ? (
				<div className="px-4 py-10 text-center text-[12px] text-mute">
					{error ? '用量数据没读到，上面写了原因；恢复后点右上角刷新重试。' : '正在准备用量数据…'}
				</div>
			) : null}
		</section>
	);
}

/** 用量页主面（保留既有导出名，容器职责已从"快照报告"改为"实时账本 + 降级快照"）。 */
export function A3SnapshotPanel({active}: {active: boolean}) {
	return (
		<PageShell wide>
			<div className="mx-auto w-full max-w-[1400px]">
				<UsagePageBody active={active} />
			</div>
		</PageShell>
	);
}
