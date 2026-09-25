/**
 * DiagnosticsPanel.tsx — XEYO 诊断中心页面（与用量页同级的页面视图）。
 *
 * 结构：左列 = 会话 / 运行选择（GET /v1/diagnostics/runs）；右列 = 一次运行的四个视图
 * （问题 / 步骤 / 上下文 / 用量）+ 实验。工具条上另有 导出 Markdown、标记这轮结果不对、
 * 采集开关。
 *
 * 分层：取数与异步纪律全在 useDiagnosticsData.ts（请求身份 / 中止 / 轮询 / 合并），
 * 措辞与纯函数在 model.ts，本文件只做接线与呈现。
 *
 * 数据纪律：
 * - 只读为主，写入只有 pin / capture 两类；页面不触发任何付费实验。
 * - 后端未给的字段一律显示破折号或「未取回」，不补默认值。
 * - 错误不挡数据：刷新失败在正文上方给出中文错误 + 重试，底下的数据照常呈现。
 */
import {useCallback, useEffect, useMemo, useState} from 'react';
import {useSearchParams} from 'react-router-dom';
import {Download, Loader2, Pin, RotateCw, Stethoscope} from 'lucide-react';
import {PageShell} from '@/components/PageShell';
import {
	fetchDiagReportMarkdown,
	type DiagRunsResult,
} from '@/lib/api/diagnostics';
import {useChatStore} from '@/stores/chatStore';
import {activeBackendSessionId} from '@/stores/chat/preStoreHelpers';
import {toast} from '@/lib/toast';
import {cn} from '@/lib/utils';
import {
	CAPTURE_NOTE,
	DASH,
	NO_RUNS_IN_TAIL_TEXT,
	STALE_REFRESH_SUFFIX,
	boundaryCoverageOfRun,
	fmtBytes,
	fmtClock,
	fmtInt,
	linkMismatchText,
	pinKindLabel,
} from './model';
import {ContextView} from './ContextView';
import {ExperimentsView} from './ExperimentsView';
import {FindingsView} from './FindingsView';
import {PinForm} from './PinForm';
import {SessionPicker} from './SessionPicker';
import {StepsView} from './StepsView';
import {UsageView} from './UsageView';
import {useDiagnosticsData} from './useDiagnosticsData';
import {Badge, Notice, Section} from './ui';

const TABS = [
	{key: 'problems', label: '问题'},
	{key: 'steps', label: '步骤'},
	{key: 'context', label: '上下文'},
	{key: 'usage', label: '用量'},
	{key: 'experiments', label: '实验'},
] as const;

type TabKey = (typeof TABS)[number]['key'];

const DEFAULT_TAB: TabKey = 'problems';

function tabFromParam(raw: string | null): TabKey {
	return TABS.find(t => t.key === raw)?.key ?? DEFAULT_TAB;
}

/** GUI 会话 → 后端 session_id（复用 chat store 的同一解析口径）。 */
function useBackendSessions(): Array<{id: string; label: string}> {
	const sessions = useChatStore(s => s.sessions);
	const historyById = useChatStore(s => s.historyById);
	return useMemo(
		() =>
			sessions
				.filter(s => !s.id.startsWith('side-'))
				.map(s => {
					const id = activeBackendSessionId(historyById, s.id);
					return {
						id,
						// 没有标题时退回**完整 id**：原先截到 8 位，而 GUI id 一律以
						// `sess_` 开头 ⇒ 两条未命名会话在列表里长成同一个名字。
						label: s.title?.trim() || id,
					};
				}),
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
		return <p className="xy-dig-empty">{NO_RUNS_IN_TAIL_TEXT}</p>;
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

/** 中文错误 + 重试；离线态与后端 4xx/5xx 都走这一条路径，不出现浏览器原文。 */
function ErrorBox({
	message,
	hint,
	onRetry,
	retrying,
}: {
	message: string;
	hint?: string;
	onRetry: () => void;
	retrying: boolean;
}) {
	return (
		<div className="xy-dig-error">
			<span className="block">{message}</span>
			{hint ? <span className="mt-1 block opacity-80">{hint}</span> : null}
			<div className="xy-dig-actions mt-2">
				<button type="button" className="xy-dig-btn" onClick={onRetry} disabled={retrying}>
					{retrying ? (
						<Loader2 className="size-3 animate-spin" aria-hidden />
					) : (
						<RotateCw className="size-3" aria-hidden />
					)}
					重试
				</button>
			</div>
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
	// 深链只在首次挂载读一次（/diagnostics?session=<id>&turn=<id>&tool=<id>）。
	const deepLink = useMemo(
		() => ({
			session: params.get('session') ?? '',
			turn: params.get('turn') ?? '',
			tool: params.get('tool') ?? '',
			tab: params.get('tab') ?? '',
		}),
		// 只在挂载时取一次：后续 URL 由本组件写回，不能让回退/前进反过来改写选择。
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[],
	);
	const [sessionId, setSessionId] = useState(
		() => deepLink.session || activeBackendId || '',
	);
	const [tab, setTab] = useState<TabKey>(() => tabFromParam(deepLink.tab));
	const [pinOpen, setPinOpen] = useState(false);
	const [exportBusy, setExportBusy] = useState(false);
	// 看过的标签保留挂载（隐藏而非销毁）：换标签不该丢掉跑了 60s 的事实定位结果，
	// 也不该把填了一半的实验配置清空。没看过的标签不挂载，避免白白发一次实验列表请求。
	const [seenTabs, setSeenTabs] = useState<ReadonlySet<TabKey>>(() => new Set<TabKey>([tab]));
	useEffect(() => {
		setSeenTabs(prev => (prev.has(tab) ? prev : new Set<TabKey>([...prev, tab])));
	}, [tab]);

	const data = useDiagnosticsData({active, sessionId, deepLink});
	const {turnId} = data;

	// 选择 → URL（保持可分享 / 可回退的深链；replace 不堆历史）。
	// tab 与未消费的 tool 也进 URL：刷新 / 后退不再回到空白的「问题」页。
	useEffect(() => {
		if (!active) return;
		const next = new URLSearchParams();
		if (sessionId) next.set('session', sessionId);
		if (turnId) next.set('turn', turnId);
		if (tab !== DEFAULT_TAB) next.set('tab', tab);
		if (data.linkTool) next.set('tool', data.linkTool);
		const qs = next.toString();
		if (params.toString() !== qs) setParams(next, {replace: true});
	}, [active, sessionId, turnId, tab, data.linkTool, params, setParams]);

	// 会话列表默认选中当前会话（深链优先）。
	useEffect(() => {
		if (sessionId || !activeBackendId) return;
		setSessionId(activeBackendId);
	}, [activeBackendId, sessionId]);

	// 换会话与换轮次都不该留着标记表单：它固定的是"当前这一轮"的证据。
	useEffect(() => {
		setPinOpen(false);
	}, [sessionId, turnId]);

	const pickTurn = useCallback(
		(next: string) => {
			data.selectTurn(next);
			data.clearLink();
		},
		[data],
	);

	const pickSession = useCallback(
		(next: string) => {
			setSessionId(next);
			setPinOpen(false);
		},
		[],
	);

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

	const contentKey = `${sessionId}:${turnId}`;
	const tabIdx = Math.max(0, TABS.findIndex(t => t.key === tab));
	const onTabKeyDown = (e: React.KeyboardEvent) => {
		if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
		e.preventDefault();
		const dir = e.key === 'ArrowRight' ? 1 : -1;
		const next = (tabIdx + dir + TABS.length) % TABS.length;
		setTab(TABS[next]!.key);
	};

	const {runs, detail} = data;
	// 「尾窗截断」只在真的有记录时说截断：没有审计行不等于被截断（见列表空态措辞）。
	const runsTruncated = !!runs && runs.runs.length > 0 && !runs.complete;

	const toolbar = (
		<>
			<SessionPicker
				sessions={backendSessions}
				value={sessionId}
				onPick={id => {
					pickSession(id);
					data.clearLink();
				}}
			/>
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
			aria-busy={data.runsLoading || data.detailLoading}
		>
			<div className="xy-dig-layout">
				<aside className="xy-dig-side" aria-label="运行选择">
					<div className="xy-dig-side-head">
						<Stethoscope className="size-3.5 shrink-0 text-mute" aria-hidden />
						<span>运行</span>
						{runsTruncated ? <Badge tone="warn">尾窗截断</Badge> : null}
					</div>
					{!sessionId ? (
						<p className="xy-dig-empty">选择一个会话以列出可诊断的轮次。</p>
					) : (
						<>
							{data.runsError ? (
								<ErrorBox
									message={data.runsError}
									onRetry={() => data.reloadRuns(false)}
									retrying={data.runsLoading}
								/>
							) : null}
							{data.runsLoading && !runs ? (
								<div className="xy-dig-loading">
									<div className="xy-dig-skeleton" />
									<div className="xy-dig-skeleton" />
									<div className="xy-dig-skeleton" />
								</div>
							) : (
								<RunPicker runs={runs} value={turnId} onPick={pickTurn} />
							)}
						</>
					)}
					<div className="xy-dig-capture">
						<label className="xy-dig-check">
							<input
								type="checkbox"
								checked={captureIsOn(data.capture)}
								// 采集状态没取回时不给可点但什么都不会发生的勾选框。
								disabled={!sessionId || data.capture === null || data.captureBusy}
								onChange={data.toggleCapture}
							/>
							<span>可复现记录（本机）</span>
						</label>
						<p className="xy-dig-capture-note">{CAPTURE_NOTE}</p>
						{data.capture ? (
							<p className="xy-dig-capture-bytes tabular-nums">
								采集目录已占用 {fmtBytes(data.capture.disk_bytes)}
								{data.capture.quota_bytes != null
									? ` / 配额 ${fmtBytes(data.capture.quota_bytes)}`
									: ''}
							</p>
						) : (
							<p className="xy-dig-capture-note">采集状态未取回：该端点不可达时不改动任何配置。</p>
						)}
					</div>
					{pinOpen && turnId ? (
						<PinForm
							key={contentKey}
							sessionId={sessionId}
							turnId={turnId}
							detail={detail}
							onDone={() => {
								setPinOpen(false);
								data.reloadDetail(false);
							}}
						/>
					) : null}
					{detail && detail.pins.length ? (
						<Section title="已固定的标记" dense>
							<ul className="xy-dig-list">
								{detail.pins.map(p => (
									<li key={p.pin_id}>
										<span>{pinKindLabel(p.kind)}</span>
										<span>{p.note || p.name || DASH}</span>
										{p.expected ? <span className="xy-dig-pin-exp">预期：{p.expected}</span> : null}
									</li>
								))}
							</ul>
						</Section>
					) : null}
				</aside>

				<div className="xy-dig-main">
					{data.mismatch || data.detailError ? (
						<div className="xy-dig-notices">
							{data.mismatch ? (
								<Notice tone="warn">
									{linkMismatchText(data.mismatch.kind, data.mismatch.value)}
								</Notice>
							) : null}
							{data.detailError ? (
								<ErrorBox
									message={data.detailError}
									hint={
										detail
											? STALE_REFRESH_SUFFIX
											: '诊断只读取已有记录；后端未启动或该轮次不在审计窗口内都会是这个结果。'
									}
									onRetry={() => data.reloadDetail(false)}
									retrying={data.detailLoading}
								/>
							) : null}
						</div>
					) : null}
					{data.detailLoading && !detail ? (
						<div className="xy-usage-loading pointer-events-none absolute inset-0">
							<div className="xy-usage-skeleton" />
							<div className="xy-usage-skeleton min-h-[240px]" />
						</div>
					) : !detail ? (
						<p className="xy-dig-empty">
							未选择轮次。左侧列表来自审计尾窗；列表为空不等于没有运行过。
						</p>
					) : (
						<div key={contentKey} className="xy-usage-content-switch xy-dig-panes">
							{seenTabs.has('problems') ? (
								<div className="xy-dig-view" hidden={tab !== 'problems'}>
									<FindingsView detail={detail} />
								</div>
							) : null}
							{seenTabs.has('steps') ? (
								<div className="xy-dig-view" hidden={tab !== 'steps'}>
									<StepsView
										detail={detail}
										loadingMore={data.moreLoading}
										onLoadMore={data.loadMoreEvents}
									/>
								</div>
							) : null}
							{seenTabs.has('context') ? (
								<div className="xy-dig-view" hidden={tab !== 'context'}>
									<ContextView
										detail={detail}
										sessionId={sessionId}
										turnId={turnId}
										storeRoot={runs?.store_root ?? ''}
									/>
								</div>
							) : null}
							{seenTabs.has('usage') ? (
								<div className="xy-dig-view" hidden={tab !== 'usage'}>
									<UsageView detail={detail} />
								</div>
							) : null}
							{seenTabs.has('experiments') ? (
								<div className="xy-dig-view" hidden={tab !== 'experiments'}>
									<ExperimentsView sessionId={sessionId} turnId={turnId} />
								</div>
							) : null}
						</div>
					)}
				</div>
			</div>
		</PageShell>
	);
}

/** 未取回采集状态时勾选框是禁用的，勾上与否都不能凭空显示为"已开启"。 */
function captureIsOn(capture: {enabled: boolean} | null): boolean {
	return capture?.enabled === true;
}
