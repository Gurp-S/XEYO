import {useEffect, useRef, useState} from 'react';
import {ExternalLink, FileText, RefreshCw} from 'lucide-react';
import {A3NativePanel} from '@/components/A3NativePanel';
import {
	getMemoryReport,
	getMemoryReportData,
	memoryReportViewUrl,
	runMemorySnapshot,
	type A3ReportData,
	type MemoryReportInfo,
} from '@/lib/api';
import {openExternalUrl} from '@/lib/openExternal';
import {toast} from '@/lib/toast';
import {cn} from '@/lib/utils';

/**
 * 数据面读不出来时给用户的中文说法（R5：退回 iframe，同时讲清为什么）。
 *
 * 只按服务端回的结构化 `type` 分类，不把英文原文糊到界面上；认不得的 type 一律说
 * "没接通"并把原因括在后面——界面不猜，也不写裸 Not Found。
 */
function a3DataFailureText(message: string): string {
	const m = message.toLowerCase();
	if (m.includes('not_found') || m.includes('not generated')) {
		return '报告数据读不出来（A3 报告还没生成）';
	}
	if (m.includes('memory_report_unparsable')) {
		return '报告数据读不出来（报告里的内嵌数据解析失败）';
	}
	if (m.includes('memory_report_unreadable')) {
		return '报告数据读不出来（报告文件读不出来）';
	}
	if (m.includes('localhost') || m.includes('permission')) {
		return '报告数据读不出来（这份报告只允许本机读取）';
	}
	return `报告数据读不出来（${message || 'unknown'}），暂用网页视图顶上`;
}

function bytesLabel(bytes?: number): string | null {
	if (!bytes || bytes <= 0) return null;
	if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
	if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
	return `${bytes} B`;
}

function generatedLabel(iso?: string | null): string | null {
	if (!iso) return null;
	const date = new Date(iso);
	if (Number.isNaN(date.getTime())) return iso;
	return date.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
}

/** A3 日监控报告放在用量页面统一查看，设置页不再重复放置快照入口。 */
export function A3SnapshotPanel({active}: {active: boolean}) {
	const [report, setReport] = useState<MemoryReportInfo | null>(null);
	const [data, setData] = useState<A3ReportData | null>(null);
	const [dataFailure, setDataFailure] = useState('');
	const [loading, setLoading] = useState(false);
	const [running, setRunning] = useState(false);
	const [opening, setOpening] = useState(false);
	const [snapshotResult, setSnapshotResult] = useState('');
	const [reportError, setReportError] = useState('');
	const [reportRevision, setReportRevision] = useState(0);
	const reportRequestRef = useRef(0);
	const dataRequestRef = useRef(0);
	const snapshotInFlightRef = useRef(false);
	const mountedRef = useRef(true);

	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
			reportRequestRef.current += 1;
			dataRequestRef.current += 1;
		};
	}, []);

	useEffect(() => {
		if (!active) return;
		let disposed = false;
		const requestId = ++reportRequestRef.current;
		setLoading(true);
		void getMemoryReport().then(r => {
			if (disposed || reportRequestRef.current !== requestId) return;
			if (r.ok && r.data) {
				setReport(r.data);
				setReportError('');
			} else {
				setReport(null);
				setReportError(`未读到 A3 报告状态（${r.message || 'unknown'}）`);
			}
		}).catch(error => {
			if (!disposed && reportRequestRef.current === requestId) {
				setReportError(error instanceof Error ? error.message : '读取 A3 报告失败');
			}
		}).finally(() => {
			if (!disposed && reportRequestRef.current === requestId) setLoading(false);
		});
		return () => {
			disposed = true;
		};
	}, [active]);

	/**
	 * 报告的结构化数据：成功走原生视图，失败退回 iframe（R5）。
	 *
	 * 等状态查询确认**报告存在**再取数据（`report.exists` 是面板自己用的那一份权威，
	 * 未确认存在时发请求只会换回一个 404）。刷新（`reportRevision`，含快照补齐后那次）
	 * 重取一次；重取期间**保留旧数据**，不闪加载态。
	 */
	useEffect(() => {
		if (!active || !report?.exists) return;
		const requestId = ++dataRequestRef.current;
		void getMemoryReportData()
			.then(r => {
				if (!mountedRef.current || dataRequestRef.current !== requestId) return;
				if (r.ok && r.data) {
					setData(r.data);
					setDataFailure('');
				} else {
					setData(null);
					setDataFailure(a3DataFailureText(r.message));
				}
			})
			.catch(error => {
				if (!mountedRef.current || dataRequestRef.current !== requestId) return;
				setData(null);
				setDataFailure(
					a3DataFailureText(error instanceof Error ? error.message : String(error)),
				);
			});
		return () => {
			dataRequestRef.current += 1;
		};
	}, [active, reportRevision, report?.exists]);

	const refreshReport = async () => {
		const requestId = ++reportRequestRef.current;
		setLoading(true);
		try {
			const r = await getMemoryReport();
			if (!mountedRef.current || reportRequestRef.current !== requestId) return;
			if (r.ok && r.data) {
				setReport(r.data);
				setReportError('');
			} else {
				setReport(null);
				setReportError(`未读到 A3 报告状态（${r.message || 'unknown'}）`);
			}
			setReportRevision(revision => revision + 1);
		} catch (error) {
			if (!mountedRef.current || reportRequestRef.current !== requestId) return;
			setReportError(error instanceof Error ? error.message : '读取 A3 报告失败');
		} finally {
			if (mountedRef.current && reportRequestRef.current === requestId) {
				setLoading(false);
			}
		}
	};

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
			if (mountedRef.current) await refreshReport();
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

	const reportMeta = report
		? !report.exists
			? '尚未生成报告'
			: [
				report.path?.split(/[\\/]/).pop() ?? 'A3 报告',
				report.days?.length ? `${report.days.length} 天` : null,
				bytesLabel(report.bytes),
				generatedLabel(report.generated_at),
			]
				.filter(Boolean)
				.join(' · ')
		: loading
			? '正在读取报告…'
			: '尚未生成报告';

	return (
		<section className="xy-usage-section mb-5 overflow-hidden rounded-[var(--xy-radius-pane)] border border-line bg-paper">
			<div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
				<div className="min-w-0">
					<h2 className="flex items-center gap-2 text-[14px] font-medium text-ink">
						<FileText className="h-4 w-4 text-accent" aria-hidden />
						A3 日常监控快照
					</h2>
					<p className="mt-0.5 text-[11px] text-mute">
						{reportError || reportMeta}
					</p>
				</div>
				<div className="flex shrink-0 items-center gap-2">
					<button
						type="button"
						disabled={loading}
						onClick={() => void refreshReport()}
						aria-label="刷新 A3 报告状态"
						className="xy-icon-btn rounded-lg p-2 text-mute hover:bg-glass-hover hover:text-ink disabled:opacity-50"
					>
						<RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
					</button>
					<button
						type="button"
						disabled={opening || !report?.exists}
						onClick={() => void openReport()}
						className="xy-press inline-flex items-center gap-1.5 rounded-lg border border-line/70 px-3 py-1.5 text-xs text-ink-soft transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-accent disabled:opacity-50"
					>
						<ExternalLink className="h-3.5 w-3.5" aria-hidden />
						{opening ? '打开中…' : '新窗口'}
					</button>
					<button
						type="button"
						disabled={running}
						onClick={() => void runSnapshot()}
						className="xy-press rounded-lg border border-accent/50 bg-accent-soft px-3 py-1.5 text-xs text-accent transition-colors hover:bg-accent/15 disabled:opacity-50"
					>
						{running ? '快照中…' : '立即快照'}
					</button>
				</div>
			</div>
			{snapshotResult ? (
				<p className="border-b border-line/60 px-4 py-2 text-[11px] text-ok" role="status">
					快照完成 · {snapshotResult}
				</p>
			) : null}
			{active && report?.exists ? (
				data ? (
					<A3NativePanel data={data} />
				) : dataFailure ? (
					/* R5 兜底：数据面读不出来才回网页视图，并写明为什么是网页。 */
					<>
						<p
							className="border-b border-line px-4 py-2 text-[11px] text-warn"
							role="status"
						>
							{dataFailure}
						</p>
						<iframe
							key={reportRevision}
							title="A3 日常监控报告"
							src={`${memoryReportViewUrl()}?v=${reportRevision}`}
							loading="lazy"
							className="block h-[min(68vh,820px)] min-h-[460px] w-full bg-white"
						/>
					</>
				) : (
					<div className="px-4 py-10 text-center text-[12px] text-mute">
						正在读取报告数据…
					</div>
				)
			) : (
				<div className="px-4 py-10 text-center text-[12px] text-mute">
					{loading
						? '正在读取 A3 报告…'
						: reportError
							? '报告状态没读到，上面写了原因；恢复后点右上角刷新重试。'
							: '还没有 A3 快照。点击“立即快照”生成报告。'}
				</div>
			)}
		</section>
	);
}
