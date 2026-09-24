/**
 * DiagnosticsPanel.tsx — XEYO 诊断中心页面（与用量页同级的页面视图）。
 *
 * 结构：左列 = 会话 / 运行选择（GET /v1/diagnostics/runs）；右列 = 一次运行的四个视图
 * （问题 / 步骤 / 上下文 / 用量）+ 实验。工具条上另有 导出 Markdown、标记这轮结果不对、
 * 采集开关。
 *
 * 数据纪律：
 * - 只读为主，写入只有 pin / capture 两类；页面不触发任何付费实验。
 * - 后端未给的字段一律显示破折号或「未取回」，不补默认值。
 * - 轮询沿用用量页口径：载入后 20s 静默刷新 + focus / visibilitychange 补一次。
 */
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {useSearchParams} from 'react-router-dom';
import {Download, Loader2, Pin, Stethoscope} from 'lucide-react';
import {PageShell} from '@/components/PageShell';
import {
	fetchDiagCapture,
	fetchDiagReportMarkdown,
	fetchDiagRun,
	fetchDiagRunEvents,
	fetchDiagRuns,
	pinDiagRun,
	setDiagCapture,
	type DiagCaptureState,
	type DiagRunDetail,
	type DiagRunsResult,
} from '@/lib/api/diagnostics';
import {useChatStore} from '@/stores/chatStore';
import {activeBackendSessionId} from '@/stores/chat/preStoreHelpers';
import {toast} from '@/lib/toast';
import {cn} from '@/lib/utils';
import {
	CAPTURE_NOTE,
	DASH,
	boundaryCoverageOfRun,
	fmtClock,
	fmtInt,
} from './model';
import {ContextView} from './ContextView';
import {ExperimentsView} from './ExperimentsView';
import {FindingsView} from './FindingsView';
import {StepsView} from './StepsView';
import {UsageView} from './UsageView';
import {Badge, Notice, Section} from './ui';

const TABS = [
	{key: 'problems', label: '问题'},
	{key: 'steps', label: '步骤'},
	{key: 'context', label: '上下文'},
	{key: 'usage', label: '用量'},
	{key: 'experiments', label: '实验'},
] as const;

type TabKey = (typeof TABS)[number]['key'];

const REFRESH_MS = 20_000;

/** GUI 会话 → 后端 session_id（复用 chat store 的同一解析口径）。 */
function useBackendSessions(): Array<{id: string; label: string}> {
	const sessions = useChatStore(s => s.sessions);
	const historyById = useChatStore(s => s.historyById);
	return useMemo(
		() =>
			sessions
				.filter(s => !s.id.startsWith('side-'))
				.map(s => ({
					id: activeBackendSessionId(historyById, s.id),
					label: s.title?.trim() || s.id.slice(0, 8),
				})),
		[sessions, historyById],
	);
}

function RunPicker({
	runs,
	value,
	onPick,
}: {
	runs: DiagRunsResult | null;
	value: string;
	onPick: (turnId: string) => void;
}) {
	if (!runs) return null;
	if (runs.runs.length === 0) {
		return (
			<p className="xy-dig-empty">
				该会话在当前审计尾窗里没有可列出的轮次。无记录不等于没有发生过轮次 ——
				尾窗之外的更早轮次不在列表范围内。
			</p>
		);
	}
	return (
		<ul className="xy-dig-runs">
			{runs.runs.map(r => {
				const cov = boundaryCoverageOfRun(r);
				const on = r.turn_id === value;
				return (
					<li key={r.turn_id || '(无轮次身份)'}>
						<button
							type="button"
							className={cn('xy-dig-run', on && 'is-on')}
							aria-pressed={on}
							onClick={() => onPick(r.turn_id)}
						>
							<span className="xy-dig-run-top">
								<span className="xy-dig-run-id font-mono">{r.turn_id || DASH}</span>
								<span className="xy-dig-run-ts tabular-nums">{fmtClock(r.last_ts)}</span>
							</span>
							<span className="xy-dig-run-counts tabular-nums">
								模型 {fmtInt(r.model_request_count)} · 工具 {fmtInt(r.tool_call_count)}
							</span>
							<span className="xy-dig-run-bar" aria-hidden>
								{cov.map((c, i) => (
									<span
										key={i}
										className={cn('xy-dig-run-cell', c.present && 'is-on')}
										title={`${c.label}：${c.present ? '有记录' : '无记录'}`}
									/>
								))}
							</span>
							<span className="xy-dig-run-cov tabular-nums">
								边界 {cov.filter(c => c.present).length}/{cov.length}
							</span>
							{r.coverage_note ? (
								<span className="xy-dig-run-note">{r.coverage_note}</span>
							) : null}
						</button>
					</li>
				);
			})}
		</ul>
	);
}

function PinForm({
	sessionId,
	turnId,
	detail,
	onDone,
}: {
	sessionId: string;
	turnId: string;
	detail: DiagRunDetail | null;
	onDone: () => void;
}) {
	const [note, setNote] = useState('');
	const [expected, setExpected] = useState('');
	const [pinEvidence, setPinEvidence] = useState(true);
	const [busy, setBusy] = useState(false);
	const [err, setErr] = useState('');

	const evidence = useMemo(() => {
		if (!detail || !pinEvidence) return [];
		const seen = new Set<string>();
		const out: DiagRunDetail['findings'][number]['evidence'] = [];
		for (const f of detail.findings) {
			for (const e of f.evidence) {
				const k = `${e.source}|${e.locator}|${e.ref_id}|${e.detail}`;
				if (seen.has(k)) continue;
				seen.add(k);
				out.push(e);
			}
		}
		for (const bd of detail.boundaries) {
			for (const e of bd.evidence) {
				const k = `${e.source}|${e.locator}|${e.ref_id}|${e.detail}`;
				if (seen.has(k)) continue;
				seen.add(k);
				if (out.length < 60) out.push(e);
			}
		}
		return out.slice(0, 60);
	}, [detail, pinEvidence]);

	return (
		<div className="xy-dig-pin">
			<label className="xy-dig-field">
				<span>这轮哪里不对（必填）</span>
				<textarea
					className="xy-dig-textarea"
					value={note}
					maxLength={4000}
					placeholder="只写观察到的事实与结果，不写推测"
					onChange={e => setNote(e.target.value)}
				/>
			</label>
			<label className="xy-dig-field">
				<span>预期结果</span>
				<textarea
					className="xy-dig-textarea"
					value={expected}
					maxLength={4000}
					placeholder="你期望这一轮产出什么"
					onChange={e => setExpected(e.target.value)}
				/>
			</label>
			<label className="xy-dig-check">
				<input
					type="checkbox"
					checked={pinEvidence}
					onChange={e => setPinEvidence(e.target.checked)}
				/>
				<span>固定证据（含本轮结论与边界证据 {evidence.length ? `${evidence.length} 条` : ''}）</span>
			</label>
			<div className="xy-dig-actions">
				<button
					type="button"
					className="xy-dig-btn is-primary"
					disabled={busy || !note.trim()}
					onClick={() => {
						setBusy(true);
						setErr('');
						pinDiagRun(sessionId, turnId, {
							note: note.trim(),
							expected: expected.trim(),
							evidence,
						})
							.then(r => {
								if (!r.ok) {
									setErr(r.error || '固定失败');
									return;
								}
								toast.success('已标记这轮结果并固定证据');
								setNote('');
								setExpected('');
								onDone();
							})
							.catch(e => setErr(e instanceof Error ? e.message : String(e)))
							.finally(() => setBusy(false));
					}}
				>
					{busy ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
					标记并固定
				</button>
			</div>
			{err ? <Notice tone="fail">{err}</Notice> : null}
			<Notice tone="info">标记只写入诊断目录的固定证据，不触发付费实验，也不修改任务内容。</Notice>
		</div>
	);
}

export function DiagnosticsPanel({active}: {active: boolean}) {
	const backendSessions = useBackendSessions();
	const activeId = useChatStore(s => s.activeId);
	const historyById = useChatStore(s => s.historyById);
	const activeBackendId = activeId
		? activeBackendSessionId(historyById, activeId)
		: null;

	const [params, setParams] = useSearchParams();
	// 深链只在首次挂载读一次（/diagnostics?session=<id>&turn=<id>）。
	const deepLinkRef = useRef({
		session: params.get('session') ?? '',
		turn: params.get('turn') ?? '',
	});
	const [sessionId, setSessionId] = useState(
		() => deepLinkRef.current.session || activeBackendId || '',
	);
	const [turnId, setTurnId] = useState(() => deepLinkRef.current.turn);
	const [tab, setTab] = useState<TabKey>('problems');
	const [runs, setRuns] = useState<DiagRunsResult | null>(null);
	const [runsLoading, setRunsLoading] = useState(false);
	const [runsError, setRunsError] = useState('');
	const [detail, setDetail] = useState<DiagRunDetail | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [detailError, setDetailError] = useState('');
	const [moreLoading, setMoreLoading] = useState(false);
	const [capture, setCapture] = useState<DiagCaptureState | null>(null);
	const [captureBusy, setCaptureBusy] = useState(false);
	const [pinOpen, setPinOpen] = useState(false);
	const [exportBusy, setExportBusy] = useState(false);

	// 选择 → URL（保持可分享 / 可回退的深链；replace 不堆历史）。
	useEffect(() => {
		if (!active) return;
		const next = new URLSearchParams();
		if (sessionId) next.set('session', sessionId);
		if (turnId) next.set('turn', turnId);
		const qs = next.toString();
		if (params.toString() !== qs) setParams(next, {replace: true});
	}, [active, sessionId, turnId, params, setParams]);

	const loadRuns = useCallback(
		(silent: boolean) => {
			if (!sessionId) {
				setRuns(null);
				return;
			}
			if (!silent) {
				setRunsLoading(true);
				setRunsError('');
			}
			fetchDiagRuns(sessionId, {limit: 80})
				.then(data => {
					setRuns(data);
					setTurnId(cur =>
						cur && data.runs.some(r => r.turn_id === cur)
							? cur
							: (deepLinkRef.current.turn &&
									data.runs.some(r => r.turn_id === deepLinkRef.current.turn)
									? deepLinkRef.current.turn
									: (data.runs[0]?.turn_id ?? '')),
					);
				})
				.catch(err => {
					if (!silent) {
						setRunsError(err instanceof Error ? err.message : String(err));
						setRuns(null);
					}
				})
				.finally(() => {
					if (!silent) setRunsLoading(false);
				});
		},
		[sessionId],
	);

	const loadDetail = useCallback(
		(silent: boolean) => {
			if (!sessionId || !turnId) {
				setDetail(null);
				return;
			}
			if (!silent) {
				setDetailLoading(true);
				setDetailError('');
			}
			fetchDiagRun(sessionId, turnId)
				.then(data => setDetail(data))
				.catch(err => {
					if (!silent) {
						setDetailError(err instanceof Error ? err.message : String(err));
						setDetail(null);
					}
				})
				.finally(() => {
					if (!silent) setDetailLoading(false);
				});
		},
		[sessionId, turnId],
	);

	// 会话列表默认选中当前会话（深链优先）。
	useEffect(() => {
		if (sessionId || !activeBackendId) return;
		setSessionId(activeBackendId);
	}, [activeBackendId, sessionId]);

	useEffect(() => {
		if (!active) return;
		let cancelled = false;
		loadRuns(false);
		const timer = window.setInterval(() => {
			if (!cancelled && document.visibilityState === 'visible') loadRuns(true);
		}, REFRESH_MS);
		const onVis = () => {
			if (document.visibilityState === 'visible') loadRuns(true);
		};
		window.addEventListener('focus', onVis);
		document.addEventListener('visibilitychange', onVis);
		return () => {
			cancelled = true;
			window.clearInterval(timer);
			window.removeEventListener('focus', onVis);
			document.removeEventListener('visibilitychange', onVis);
		};
		// loadRuns 随 sessionId 变化；active 只在页面视图打开时启用轮询。
	}, [active, loadRuns]);

	useEffect(() => {
		if (!active) return;
		let cancelled = false;
		loadDetail(false);
		const timer = window.setInterval(() => {
			if (!cancelled && document.visibilityState === 'visible') loadDetail(true);
		}, REFRESH_MS);
		const onVis = () => {
			if (document.visibilityState === 'visible') loadDetail(true);
		};
		window.addEventListener('focus', onVis);
		document.addEventListener('visibilitychange', onVis);
		return () => {
			cancelled = true;
			window.clearInterval(timer);
			window.removeEventListener('focus', onVis);
			document.removeEventListener('visibilitychange', onVis);
		};
	}, [active, loadDetail]);

	useEffect(() => {
		if (!active || !sessionId) {
			setCapture(null);
			return;
		}
		let cancelled = false;
		fetchDiagCapture(sessionId)
			.then(c => {
				if (!cancelled) setCapture(c);
			})
			.catch(() => {
				if (!cancelled) setCapture(null);
			});
		return () => {
			cancelled = true;
		};
	}, [active, sessionId]);

	const loadMoreEvents = useCallback(() => {
		if (!sessionId || !turnId || !detail) return;
		setMoreLoading(true);
		const offset = detail.event_offset + detail.event_limit;
		fetchDiagRunEvents(sessionId, turnId, offset, detail.event_limit || undefined)
			.then(page => {
				setDetail(cur =>
					cur
						? {
								...cur,
								events: [...cur.events, ...page.events],
								event_total: page.total,
								events_complete: page.complete,
								next_event_cursor: page.nextCursor,
								event_offset: offset,
							}
						: cur,
				);
			})
			.catch(err => toast.error(err instanceof Error ? err.message : String(err)))
			.finally(() => setMoreLoading(false));
	}, [sessionId, turnId, detail]);

	const toggleCapture = useCallback(() => {
		if (!sessionId || !capture) return;
		setCaptureBusy(true);
		setDiagCapture(sessionId, !capture.enabled)
			.then(next => {
				setCapture({...next, disk_bytes: capture.disk_bytes, quota_bytes: capture.quota_bytes});
				toast.success(next.enabled ? '已开启可复现记录' : '已关闭可复现记录');
			})
			.catch(err => toast.error(err instanceof Error ? err.message : String(err)))
			.finally(() => setCaptureBusy(false));
	}, [sessionId, capture]);

	const exportMarkdown = useCallback(() => {
		if (!sessionId || !turnId) return;
		setExportBusy(true);
		fetchDiagReportMarkdown(sessionId, turnId)
			.then(({markdown}) => {
				const blob = new Blob([markdown], {type: 'text/markdown;charset=utf-8'});
				const url = URL.createObjectURL(blob);
				const a = document.createElement('a');
				a.href = url;
				a.download = `xeyo-diagnostics-${turnId}.md`;
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				window.setTimeout(() => URL.revokeObjectURL(url), 2000);
				toast.success('已导出 Markdown 报告');
			})
			.catch(err => toast.error(err instanceof Error ? err.message : String(err)))
			.finally(() => setExportBusy(false));
	}, [sessionId, turnId]);

	const contentKey = `${sessionId}:${turnId}:${tab}`;
	const tabIdx = Math.max(0, TABS.findIndex(t => t.key === tab));
	const onTabKeyDown = (e: React.KeyboardEvent) => {
		if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
		e.preventDefault();
		const dir = e.key === 'ArrowRight' ? 1 : -1;
		const next = (tabIdx + dir + TABS.length) % TABS.length;
		setTab(TABS[next]!.key);
	};

	const toolbar = (
		<>
			<label className="xy-dig-session">
				<span className="sr-only">会话</span>
				<select
					value={sessionId}
					onChange={e => {
						setSessionId(e.target.value);
						setTurnId('');
						deepLinkRef.current = {session: e.target.value, turn: ''};
					}}
				>
					<option value="">选择会话</option>
					{backendSessions.map(s => (
						<option key={s.id} value={s.id}>
							{s.label}
						</option>
					))}
				</select>
			</label>
			<div role="tablist" aria-label="诊断视图" onKeyDown={onTabKeyDown} className="xy-dig-tabs">
				{TABS.map(t => (
					<button
						key={t.key}
						type="button"
						role="tab"
						aria-selected={tab === t.key}
						tabIndex={tab === t.key ? 0 : -1}
						onClick={() => setTab(t.key)}
						className={cn('xy-dig-tab', tab === t.key && 'is-on')}
					>
						{t.label}
					</button>
				))}
			</div>
			<div className="ml-auto flex items-center gap-2">
				<button
					type="button"
					className="xy-dig-btn"
					disabled={!turnId || exportBusy}
					onClick={exportMarkdown}
				>
					{exportBusy ? (
						<Loader2 className="size-3 animate-spin" aria-hidden />
					) : (
						<Download className="size-3" aria-hidden />
					)}
					导出 Markdown
				</button>
				<button
					type="button"
					className="xy-dig-btn"
					disabled={!turnId}
					aria-expanded={pinOpen}
					onClick={() => setPinOpen(v => !v)}
				>
					<Pin className="size-3" aria-hidden />
					标记这轮结果不对
				</button>
			</div>
		</>
	);

	return (
		<PageShell
			wide
			toolbar={toolbar}
			data-testid="diagnostics-panel"
			aria-busy={runsLoading || detailLoading}
		>
			<div className="xy-dig-layout">
				<aside className="xy-dig-side" aria-label="运行选择">
					<div className="xy-dig-side-head">
						<Stethoscope className="size-3.5 shrink-0 text-mute" aria-hidden />
						<span>运行</span>
						{runs && !runs.complete ? <Badge tone="warn">尾窗截断</Badge> : null}
					</div>
					{!sessionId ? (
						<p className="xy-dig-empty">选择一个会话以列出可诊断的轮次。</p>
					) : runsError ? (
						<p className="xy-dig-error">{runsError}</p>
					) : runsLoading && !runs ? (
						<div className="xy-dig-loading">
							<div className="xy-dig-skeleton" />
							<div className="xy-dig-skeleton" />
							<div className="xy-dig-skeleton" />
						</div>
					) : (
						<RunPicker runs={runs} value={turnId} onPick={setTurnId} />
					)}
					<div className="xy-dig-capture">
						<label className="xy-dig-check">
							<input
								type="checkbox"
								checked={capture?.enabled === true}
								disabled={!sessionId || captureBusy}
								onChange={toggleCapture}
							/>
							<span>可复现记录（本机）</span>
						</label>
						<p className="xy-dig-capture-note">{CAPTURE_NOTE}</p>
						{capture ? (
							<p className="xy-dig-capture-bytes tabular-nums">
								已占用 {capture.disk_bytes == null ? DASH : `${(capture.disk_bytes / 1024).toFixed(0)} KB`}
								{capture.quota_bytes != null
									? ` / 配额 ${(capture.quota_bytes / 1024 / 1024).toFixed(0)} MB`
									: ''}
							</p>
						) : (
							<p className="xy-dig-capture-note">采集状态未取回：该端点不可达时不改动任何配置。</p>
						)}
					</div>
					{pinOpen && turnId ? (
						<PinForm
							sessionId={sessionId}
							turnId={turnId}
							detail={detail}
							onDone={() => {
								setPinOpen(false);
								loadDetail(true);
							}}
						/>
					) : null}
					{detail && detail.pins.length ? (
						<Section title="已固定的标记" dense>
							<ul className="xy-dig-list">
								{detail.pins.map(p => (
									<li key={p.pin_id}>
										<span className="font-mono">{p.kind || 'pin'}</span>
										<span>{p.note || p.name || DASH}</span>
										{p.expected ? <span className="xy-dig-pin-exp">预期：{p.expected}</span> : null}
									</li>
								))}
							</ul>
						</Section>
					) : null}
				</aside>

				<div className="xy-dig-main">
					{detailError ? (
						<p className="xy-dig-error">
							{detailError}
							<span className="mt-1 block text-mute">
								诊断只读取已有记录；后端未启动或该轮次不在审计窗口内都会是这个结果。
							</span>
						</p>
					) : detailLoading && !detail ? (
						<div className="xy-usage-loading pointer-events-none absolute inset-0">
							<div className="xy-usage-skeleton" />
							<div className="xy-usage-skeleton min-h-[240px]" />
						</div>
					) : !detail ? (
						<p className="xy-dig-empty">
							未选择轮次。左侧列表来自审计尾窗；列表为空不等于没有运行过。
						</p>
					) : (
						<div key={contentKey} className="xy-usage-content-switch xy-dig-view">
							{tab === 'problems' ? <FindingsView detail={detail} /> : null}
							{tab === 'steps' ? (
								<StepsView
									detail={detail}
									loadingMore={moreLoading}
									onLoadMore={loadMoreEvents}
								/>
							) : null}
							{tab === 'context' ? (
								<ContextView
									detail={detail}
									sessionId={sessionId}
									turnId={turnId}
									storeRoot={runs?.store_root ?? ''}
								/>
							) : null}
							{tab === 'usage' ? <UsageView detail={detail} /> : null}
							{tab === 'experiments' ? (
								<ExperimentsView sessionId={sessionId} turnId={turnId} />
							) : null}
						</div>
					)}
				</div>
			</div>
		</PageShell>
	);
}
