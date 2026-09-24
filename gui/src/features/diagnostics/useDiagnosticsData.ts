/**
 * features/diagnostics/useDiagnosticsData.ts — 诊断页的数据装载层（唯一的取数入口）。
 *
 * 这里管的是**异步纪律**，与措辞层 model.ts、视图层各 View 分开：
 * 1. 每条链路一个单调递增的请求身份：只有最新一次请求的结果能落 state，
 *    慢的旧响应（服务端要重扫审计 + usage + transcript 尾窗，客户端 60s 超时）
 *    即使后到也只能被丢弃，否则列表高亮 B 而正文全是 A。
 * 2. 载荷自证身份：detail 带 turn_id、runs 带 session_id，与所请求的不一致就丢弃。
 * 3. 在飞的请求用 AbortController 取消：60s 的全尾扫描会占住同 host 的连接槽。
 * 4. 每个 loader 一个在飞标记：20s 轮询与 focus/visibilitychange 不叠加请求。
 * 5. 成功必须清错：一次瞬时的轮询失败不能永久挡住底下仍在更新的数据。
 */
import {useCallback, useEffect, useRef, useState} from 'react';
import {
	fetchDiagCapture,
	fetchDiagRun,
	fetchDiagRunEvents,
	fetchDiagRuns,
	isDiagRequestCancelled,
	setDiagCapture,
	type DiagCaptureState,
	type DiagRunDetail,
	type DiagRunsResult,
} from '@/lib/api/diagnostics';
import {toast} from '@/lib/toast';
import {mergeDetailPreservingLoadedPages} from './model';

const REFRESH_MS = 20_000;
const RUNS_LIMIT = 80;

/** 深链没有落到真实存在的轮次上——原样带出用户点的那个 id，不自动改选。 */
export type DiagLinkMismatch = {kind: 'tool' | 'turn'; value: string};

export type TurnSelectionAfterRuns = {
	turnId: string;
	mismatch: DiagLinkMismatch | null;
	/** 深链的 tool 参数是否已经消费掉（可从 URL 撤下）。 */
	toolResolved: boolean;
};

/**
 * 列表刷新后该选中哪一轮：
 * - 有 tool 深链：只认 tool_use_ids 命中的一轮；没命中就明确报「不在这次的窗口里」，
 *   绝不退回 runs[0]（那等于把别的轮次结论当成用户那一击的答案）；
 * - 有 turn 深链但本轮不在审计尾窗：同样不顶替；
 * - 其余情形保留当前选择，最后才默认第一条。
 */
export function selectTurnAfterRunsLoaded(args: {
	runs: DiagRunsResult;
	currentTurn: string;
	deepTurn: string;
	toolHint: string;
}): TurnSelectionAfterRuns {
	const runs = args.runs.runs;
	const has = (t: string) => !!t && runs.some(r => r.turn_id === t);
	if (args.toolHint) {
		const hit = runs.find(r => r.tool_use_ids.includes(args.toolHint));
		if (hit?.turn_id) return {turnId: hit.turn_id, mismatch: null, toolResolved: true};
		return {
			turnId: has(args.currentTurn) ? args.currentTurn : '',
			mismatch: {kind: 'tool', value: args.toolHint},
			toolResolved: false,
		};
	}
	if (has(args.currentTurn)) return {turnId: args.currentTurn, mismatch: null, toolResolved: true};
	if (args.deepTurn) {
		if (has(args.deepTurn)) return {turnId: args.deepTurn, mismatch: null, toolResolved: true};
		return {turnId: '', mismatch: {kind: 'turn', value: args.deepTurn}, toolResolved: true};
	}
	return {turnId: runs[0]?.turn_id ?? '', mismatch: null, toolResolved: true};
}

export type DiagnosticsLink = {turn: string; tool: string};

export function useDiagnosticsData(args: {
	active: boolean;
	sessionId: string;
	/** 仅首次挂载读取一次；之后由本 hook 自己消费与清理。 */
	deepLink: DiagnosticsLink;
}) {
	const {active, sessionId, deepLink} = args;

	const [turnId, setTurnIdState] = useState(() => deepLink.turn);
	const [runs, setRuns] = useState<DiagRunsResult | null>(null);
	const [runsLoading, setRunsLoading] = useState(false);
	const [runsError, setRunsError] = useState('');
	const [detail, setDetail] = useState<DiagRunDetail | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [detailError, setDetailError] = useState('');
	const [mismatch, setMismatch] = useState<DiagLinkMismatch | null>(null);
	const [linkTool, setLinkTool] = useState(() => deepLink.tool);
	const [capture, setCapture] = useState<DiagCaptureState | null>(null);
	const [captureBusy, setCaptureBusy] = useState(false);
	const [moreLoading, setMoreLoading] = useState(false);

	const turnIdRef = useRef(turnId);
	turnIdRef.current = turnId;
	const linkToolRef = useRef(linkTool);
	linkToolRef.current = linkTool;

	const deepTurnRef = useRef(deepLink.turn);
	const eventsExtendedRef = useRef(false);

	const runsReqRef = useRef(0);
	const runsBusyRef = useRef(false);
	const runsAbortRef = useRef<AbortController | null>(null);
	const detailReqRef = useRef(0);
	const detailBusyRef = useRef(false);
	const detailAbortRef = useRef<AbortController | null>(null);

	const selectTurn = useCallback((next: string) => {
		turnIdRef.current = next;
		setTurnIdState(next);
		deepTurnRef.current = '';
	}, []);

	/** 用户自己动手（换会话 / 选别的轮次）就把深链状态清掉，提示随之消失。 */
	const clearLink = useCallback(() => {
		setLinkTool('');
		setMismatch(null);
		deepTurnRef.current = '';
	}, []);

	const loadRuns = useCallback(
		(silent = false) => {
			// 忙就不叠加：必须在推进请求身份与中止旧请求之前判定，否则会把在飞的那枪
			// 误杀成"无人负责"的加载态。
			if (silent && runsBusyRef.current) return;
			const id = runsReqRef.current + 1;
			runsReqRef.current = id;
			runsAbortRef.current?.abort();
			if (!sessionId) {
				runsBusyRef.current = false;
				setRuns(null);
				setRunsError('');
				setRunsLoading(false);
				return;
			}
			const controller = new AbortController();
			runsAbortRef.current = controller;
			runsBusyRef.current = true;
			setRunsLoading(true);

			fetchDiagRuns(sessionId, {limit: RUNS_LIMIT, signal: controller.signal})
				.then(data => {
					if (runsReqRef.current !== id) return;
					// 会话 A 的慢响应不得覆盖会话 B 的列表（parseRunsResult 已带 session_id）。
					if (data.session_id && data.session_id !== sessionId) return;
					setRunsError('');
					setRuns(data);
					const sel = selectTurnAfterRunsLoaded({
						runs: data,
						currentTurn: turnIdRef.current,
						deepTurn: deepTurnRef.current,
						toolHint: linkToolRef.current,
					});
					if (sel.turnId !== turnIdRef.current) {
						turnIdRef.current = sel.turnId;
						setTurnIdState(sel.turnId);
					}
					if (sel.turnId) deepTurnRef.current = '';
					setMismatch(sel.mismatch);
					if (sel.toolResolved) setLinkTool('');
				})
				.catch(err => {
					if (runsReqRef.current !== id) return;
					if (isDiagRequestCancelled(err)) return;
					setRunsError(err instanceof Error ? err.message : String(err));
					if (!silent) setRuns(null);
				})
				.finally(() => {
					if (runsReqRef.current !== id) return;
					runsBusyRef.current = false;
					setRunsLoading(false);
				});
		},
		[sessionId],
	);

	const loadDetail = useCallback(
		(silent = false) => {
			if (silent && detailBusyRef.current) return;
			const id = detailReqRef.current + 1;
			detailReqRef.current = id;
			detailAbortRef.current?.abort();
			if (!silent) eventsExtendedRef.current = false;
			const targetTurn = turnIdRef.current;
			if (!sessionId || !targetTurn) {
				detailBusyRef.current = false;
				setDetail(null);
				setDetailError('');
				setDetailLoading(false);
				return;
			}
			const controller = new AbortController();
			detailAbortRef.current = controller;
			detailBusyRef.current = true;
			setDetailLoading(true);
			if (!silent) {
				// 换轮次必须真的看见加载态：留着上一轮的数据会把「加载中」吞掉。
				setDetail(null);
				setDetailError('');
			}

			fetchDiagRun(sessionId, targetTurn, {signal: controller.signal})
				.then(data => {
					if (detailReqRef.current !== id) return;
					// 载荷自证身份：后端把 turn_id / session_id 一起回传，不符就是错轮。
					if (data.turn_id && data.turn_id !== targetTurn) return;
					if (data.session_id && data.session_id !== sessionId) return;
					setDetailError('');
					setDetail(prev =>
						silent && prev && eventsExtendedRef.current
							? mergeDetailPreservingLoadedPages(prev, data)
							: data,
					);
				})
				.catch(err => {
					if (detailReqRef.current !== id) return;
					if (isDiagRequestCancelled(err)) return;
					setDetailError(err instanceof Error ? err.message : String(err));
					if (!silent) setDetail(null);
				})
				.finally(() => {
					if (detailReqRef.current !== id) return;
					detailBusyRef.current = false;
					setDetailLoading(false);
				});
		},
		[sessionId],
	);

	// 换会话：上一会话的一切立即作废（在飞响应由请求身份丢弃）。
	const prevSessionRef = useRef(sessionId);
	useEffect(() => {
		const prev = prevSessionRef.current;
		prevSessionRef.current = sessionId;
		if (prev === sessionId) return;
		if (!prev) return; // 首个会话是初始化，不是切换
		runsReqRef.current += 1;
		detailReqRef.current += 1;
		runsAbortRef.current?.abort();
		detailAbortRef.current?.abort();
		runsBusyRef.current = false;
		detailBusyRef.current = false;
		eventsExtendedRef.current = false;
		setRuns(null);
		setRunsError('');
		setRunsLoading(false);
		setDetail(null);
		setDetailError('');
		setDetailLoading(false);
		setMoreLoading(false);
		selectTurn('');
		clearLink();
	}, [sessionId, clearLink, selectTurn]);

	// 选中轮次变化 → 重新取详情（与 loadDetail 的会话依赖一起构成唯一入口）。
	const loadDetailRef = useRef(loadDetail);
	loadDetailRef.current = loadDetail;
	useEffect(() => {
		if (!active) return;
		loadDetailRef.current(false);
	}, [active, sessionId, turnId]);

	useEffect(() => {
		if (!active) return;
		loadRuns(false);
		const timer = window.setInterval(() => {
			if (document.visibilityState === 'visible') loadRuns(true);
		}, REFRESH_MS);
		// 只挂 visibilitychange：focus 与它同时触发会一次焦点周期发两枪全量扫描。
		const onVis = () => {
			if (document.visibilityState === 'visible') loadRuns(true);
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', onVis);
			runsAbortRef.current?.abort();
			runsReqRef.current += 1;
			runsBusyRef.current = false;
		};
	}, [active, loadRuns]);

	useEffect(() => {
		if (!active) return;
		const timer = window.setInterval(() => {
			if (document.visibilityState === 'visible') loadDetailRef.current(true);
		}, REFRESH_MS);
		const onVis = () => {
			if (document.visibilityState === 'visible') loadDetailRef.current(true);
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', onVis);
			detailAbortRef.current?.abort();
			detailReqRef.current += 1;
			detailBusyRef.current = false;
		};
	}, [active, sessionId, turnId]);

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
		const limit = detail.event_limit || undefined;
		const offset = detail.event_offset + (detail.event_limit || 0);
		setMoreLoading(true);
		fetchDiagRunEvents(sessionId, turnId, offset, limit)
			.then(page => {
				setDetail(cur => {
					if (!cur) return cur;
					const seen = new Set(cur.events.map(e => e.line_no));
					const added = page.events.filter(e => !seen.has(e.line_no));
					eventsExtendedRef.current = true;
					return {
						...cur,
						events: [...cur.events, ...added],
						event_total: page.total,
						events_complete: page.complete,
						next_event_cursor: page.nextCursor,
						event_offset: offset,
					};
				});
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

	return {
		turnId,
		selectTurn,
		runs,
		runsLoading,
		runsError,
		reloadRuns: loadRuns,
		detail,
		detailLoading,
		detailError,
		reloadDetail: loadDetail,
		mismatch,
		linkTool,
		clearLink,
		capture,
		captureBusy,
		toggleCapture,
		moreLoading,
		loadMoreEvents,
	};
}
