/**
 * ExperimentsView.tsx — 「实验」视图（设计 §7–§9）。
 *
 * 后端契约（python/server/routers/diagnostics.py::ExperimentPlanBody 与
 * diagnostics/experiments/manifest.MODES）：
 * - mode 是小写字面量 `a0|a1|a2`，大写会被服务端直接拒；
 * - 两臂的键叫 `variants: {A, B}`、次数叫 `repeat`、任务身份叫 `task_id`；
 *   多余的键（pydantic `extra='ignore'`）会被静默丢掉，所以这里一个都不发；
 * - 拒绝以 **HTTP 200 + `{ok:false,error}`** 回来（`rawJson` 已把它转成失败路径），
 *   因此"能连上"绝不等于"这个请求被接受"。
 *
 * 付费纪律：A1 / A2 会真的发模型请求，本项目未获显式授权不得付费调用。
 * 因此非 a0 的启动与任何取消都要二次确认，界面不代为授权。
 */
import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {Loader2, RefreshCw} from 'lucide-react';
import {
	cancelDiagExperiment,
	buildExperimentBody,
	listDiagExperiments,
	planDiagExperiment,
	startDiagExperiment,
	type DiagExperimentMode,
	type DiagRawResult,
} from '@/lib/api/diagnostics';
import {DASH} from './model';
import {Badge, Notice, Section} from './ui';
import {cn} from '@/lib/utils';

/** 后端任意 JSON → 只读结构树（不认识字段名，按原样键输出）。 */
function JsonView({value, depth = 0}: {value: unknown; depth?: number}) {
	if (value === null || value === undefined) {
		return <span className="xy-dig-json-null">{DASH}</span>;
	}
	if (typeof value !== 'object') {
		return <span className="xy-dig-json-leaf">{String(value)}</span>;
	}
	if (Array.isArray(value)) {
		if (value.length === 0) return <span className="xy-dig-json-null">[]</span>;
		return (
			<ul className="xy-dig-json-list">
				{value.map((v, i) => (
					<li key={i}>
						<span className="xy-dig-json-key tabular-nums">{i}</span>
						<JsonView value={v} depth={depth + 1} />
					</li>
				))}
			</ul>
		);
	}
	const entries = Object.entries(value as Record<string, unknown>);
	if (!entries.length) return <span className="xy-dig-json-null">{'{}'}</span>;
	return (
		<ul className="xy-dig-json-list">
			{entries.map(([k, v]) => (
				<li key={k} className="xy-dig-json-row">
					<span className="xy-dig-json-key">{k}</span>
					{typeof v === 'object' && v !== null ? (
						<JsonView value={v} depth={depth + 1} />
					) : (
						<span className="xy-dig-json-leaf">{v == null ? DASH : String(v)}</span>
					)}
				</li>
			))}
		</ul>
	);
}

function newIdempotencyKey(): string {
	const c = globalThis.crypto as Crypto | undefined;
	if (c?.randomUUID) return c.randomUUID();
	return `gui-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** `key` 是后端认识的 mode；`label` 只是界面上的大写编号。 */
const MODES: Array<{key: DiagExperimentMode; label: string; hint: string; billable: boolean}> = [
	{key: 'a0', label: 'A0 静态差异与确定性重算', hint: '零模型调用', billable: false},
	{key: 'a1', label: 'A1 同检查点单次响应配对', hint: '两次模型调用，不执行工具', billable: true},
	{key: 'a2', label: 'A2 隔离环境真实任务配对', hint: '两臂独立进程 + verifier', billable: true},
];

const BILLABLE_MODES = new Set<DiagExperimentMode>(
	MODES.filter(m => m.billable).map(m => m.key),
);

function modeOf(key: DiagExperimentMode) {
	return MODES.find(m => m.key === key) ?? MODES[0]!;
}

/**
 * 实验列表里可取消的身份：只认 `experiments[].experiment_id`。
 * 旧实现递归扫整个 payload 找任何 `id` 字符串，于是任何嵌套字段都会长出一个取消按钮。
 */
export function experimentIdsOf(value: unknown): string[] {
	if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
	const rows = (value as Record<string, unknown>).experiments;
	if (!Array.isArray(rows)) return [];
	const out: string[] = [];
	for (const row of rows) {
		if (!row || typeof row !== 'object') continue;
		const id = (row as Record<string, unknown>).experiment_id;
		if (typeof id === 'string' && id.trim() && !out.includes(id)) out.push(id.trim());
	}
	return out;
}

export function ExperimentsView({
	sessionId,
	turnId,
}: {
	sessionId: string;
	turnId: string;
}) {
	const [mode, setMode] = useState<DiagExperimentMode>('a0');
	const [baseline, setBaseline] = useState('');
	const [candidate, setCandidate] = useState('');
	const [repeats, setRepeats] = useState(1);
	const [budget, setBudget] = useState('');
	const [busy, setBusy] = useState<'plan' | 'start' | 'list' | 'cancel' | ''>('');
	const [plan, setPlan] = useState<DiagRawResult | null>(null);
	const [started, setStarted] = useState<DiagRawResult | null>(null);
	const [list, setList] = useState<DiagRawResult | null>(null);
	const [message, setMessage] = useState('');
	const [pending, setPending] = useState<'start' | {cancel: string} | null>(null);
	// 60s 的实验请求可能在标签页切走后才落地：组件已卸载就不再写 state。
	const mountedRef = useRef(true);
	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
		};
	}, []);

	const parseSide = (raw: string, which: string): Record<string, unknown> | null => {
		const t = raw.trim();
		if (!t) return {};
		try {
			const v = JSON.parse(t);
			if (v && typeof v === 'object' && !Array.isArray(v)) {
				return v as Record<string, unknown>;
			}
		} catch {
			/* 落到下面的错误提示 */
		}
		setMessage(`${which} 不是合法的 JSON 对象。`);
		return null;
	};

	/** 预算：只有有限非负数才进请求体。留空 = 不带这个键，界面也不谎称"会标出上限"。 */
	const budgetNumber = useMemo(() => {
		const t = budget.trim();
		if (!t) return null;
		const v = Number(t);
		return Number.isFinite(v) && v >= 0 ? v : Number.NaN;
	}, [budget]);

	const body = useCallback((): Record<string, unknown> | null => {
		const b = parseSide(baseline, '基线配置');
		if (!b) return null;
		const c = parseSide(candidate, '候选配置');
		if (!c) return null;
		if (Number.isNaN(budgetNumber)) {
			setMessage('预算上限要写成非负数字；留空表示不带该字段。');
			return null;
		}
		return buildExperimentBody({
			mode,
			sessionId,
			turnId,
			variantA: b,
			variantB: c,
			repeat: repeats,
			budgetCny: budgetNumber,
		});
	}, [baseline, budgetNumber, candidate, mode, repeats, sessionId, turnId]);

	const refreshList = useCallback(async () => {
		setBusy('list');
		const r = await listDiagExperiments();
		if (!mountedRef.current) return;
		setList(r);
		setBusy('');
	}, []);

	useEffect(() => {
		void refreshList();
	}, [refreshList]);

	const askStart = () => {
		const b = body();
		if (!b) return;
		setMessage('');
		if (BILLABLE_MODES.has(mode)) {
			// 付费调用不由界面代授权：先落地一次显式确认。
			setPending('start');
			return;
		}
		setPending(null);
		setBusy('start');
		void startDiagExperiment({...b, idempotency_key: newIdempotencyKey()}).then(r => {
			if (!mountedRef.current) return;
			setStarted(r);
			setBusy('');
			void refreshList();
		});
	};

	const confirmStart = () => {
		const b = body();
		if (!b) return;
		setPending(null);
		setBusy('start');
		void startDiagExperiment({...b, idempotency_key: newIdempotencyKey()}).then(r => {
			if (!mountedRef.current) return;
			setStarted(r);
			setBusy('');
			void refreshList();
		});
	};

	return (
		<div className="xy-dig-col">
			<Section title="实验层状态" hint="端点拒绝也按原样降级，不伪造结果">
				{/* 三档而非两档：列表尚未取回时不得先亮绿色"可访问"。 */}
				{!list ? (
					<Badge tone="neutral">列表未取回</Badge>
				) : list.ok ? (
					<Badge tone="ok">实验端点可访问</Badge>
				) : (
					<Notice tone="warn">
						实验层不可用 —— 列表端点返回 {list.error || '拒绝，且未给出原因'}
					</Notice>
				)}
				<p className="xy-dig-sub">
					本轮范围只到「生成计划」；启动真实模型实验需要用户显式配置与预算授权，
					界面不代为授权付费调用。
				</p>
			</Section>

			<Section title="实验配置" hint="一个可变项：其余变量必须一致">
				<div className="xy-dig-modes">
					{MODES.map(m => (
						<button
							key={m.key}
							type="button"
							aria-pressed={mode === m.key}
							onClick={() => {
								setMode(m.key);
								setPending(null);
							}}
							className={cn('xy-dig-mode', mode === m.key && 'is-on')}
						>
							<span className="xy-dig-mode-key">{m.key.toUpperCase()}</span>
							<span className="xy-dig-mode-label">{m.label}</span>
							<span className="xy-dig-mode-hint">{m.hint}</span>
						</button>
					))}
				</div>
				<div className="xy-dig-form">
					<label className="xy-dig-field">
						<span>基线配置（A 臂 JSON）</span>
						<textarea
							className="xy-dig-textarea font-mono"
							value={baseline}
							placeholder='{"blocks":{"system":"…"}}'
							onChange={e => setBaseline(e.target.value)}
						/>
					</label>
					<label className="xy-dig-field">
						<span>候选配置（B 臂 JSON）</span>
						<textarea
							className="xy-dig-textarea font-mono"
							value={candidate}
							placeholder='{"blocks":{"system":"…"}}'
							onChange={e => setCandidate(e.target.value)}
						/>
					</label>
					<div className="xy-dig-field-row">
						<label className="xy-dig-field">
							<span>重复次数</span>
							<input
								type="number"
								min={0}
								max={20}
								className="xy-dig-input"
								value={repeats}
								onChange={e => {
									const v = Number(e.target.value);
									setRepeats(Number.isFinite(v) ? Math.max(0, Math.min(20, Math.trunc(v))) : 0);
								}}
							/>
						</label>
						<label className="xy-dig-field">
							<span>预算上限（CNY）</span>
							<input
								type="text"
								inputMode="decimal"
								className="xy-dig-input"
								value={budget}
								placeholder="留空 = 不发送该字段"
								onChange={e => setBudget(e.target.value)}
							/>
						</label>
					</div>
				</div>
				<div className="xy-dig-actions">
					<button
						type="button"
						className="xy-dig-btn"
						disabled={busy !== ''}
						onClick={() => {
							const b = body();
							if (!b) return;
							setBusy('plan');
							setMessage('');
							setPending(null);
							void planDiagExperiment(b).then(r => {
								if (!mountedRef.current) return;
								setPlan(r);
								setBusy('');
							});
						}}
					>
						{busy === 'plan' ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
						生成计划（不发模型请求）
					</button>
					<button
						type="button"
						className="xy-dig-btn"
						disabled={busy !== ''}
						onClick={askStart}
					>
						{busy === 'start' ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
						按配置启动
					</button>
					<button
						type="button"
						className="xy-dig-btn"
						disabled={busy !== ''}
						onClick={() => void refreshList()}
					>
						{busy === 'list' ? (
							<Loader2 className="size-3 animate-spin" aria-hidden />
						) : (
							<RefreshCw className="size-3" aria-hidden />
						)}
						刷新列表
					</button>
				</div>
				{pending === 'start' ? (
					<Notice tone="warn">
						确认启动 {modeOf(mode).label}？该模式会真实发出模型请求（{modeOf(mode).hint}）
						，费用按 usage 估算、非账单实付。再点一次「确认启动」才执行；本轮未确认前不发送任何请求。
					</Notice>
				) : null}
				{message ? <Notice tone="fail">{message}</Notice> : null}
				{pending === 'start' ? (
					<div className="xy-dig-actions">
						<button
							type="button"
							className="xy-dig-btn is-primary"
							disabled={busy !== ''}
							onClick={confirmStart}
						>
							确认启动（含付费调用）
						</button>
						<button
							type="button"
							className="xy-dig-btn"
							onClick={() => {
								setPending(null);
								setMessage('');
							}}
						>
							取消，不发送
						</button>
					</div>
				) : null}
			</Section>

			{plan ? (
				<Section title="计划结果" hint="端点原文">
					{plan.ok ? <JsonView value={plan.data} /> : <Notice tone="warn">实验层拒绝该请求 —— {plan.error}</Notice>}
				</Section>
			) : null}

			{started ? (
				<Section title="启动回执" hint="端点原文">
					{started.ok ? <JsonView value={started.data} /> : <Notice tone="warn">实验层拒绝该请求 —— {started.error}</Notice>}
				</Section>
			) : null}

			{list && list.ok ? (
				<Section title="已有实验" hint="端点原文，字段不做解释">
					<JsonView value={list.data} />
					{experimentIdsOf(list.data).length ? (
						<div className="xy-dig-actions">
							{experimentIdsOf(list.data).map(id => (
								<button
									key={id}
									type="button"
									className="xy-dig-btn"
									disabled={busy !== ''}
									onClick={() => {
										if (pending !== null && typeof pending === 'object' && pending.cancel === id) {
											setPending(null);
											setBusy('cancel');
											void cancelDiagExperiment(id).then(r => {
												if (!mountedRef.current) return;
												setMessage(
													r.ok ? `已请求取消 ${id}` : `取消失败：${r.error}`,
												);
												setBusy('');
												void refreshList();
											});
											return;
										}
										setMessage('');
										setPending({cancel: id});
									}}
								>
									取消 {id}
								</button>
							))}
						</div>
					) : null}
					{pending !== null && typeof pending === 'object' ? (
						<Notice tone="warn">
							再点一次「取消 {pending.cancel}」才会发出取消请求；取消会中断该实验已排定的模型调用。
						</Notice>
					) : null}
				</Section>
			) : null}
		</div>
	);
}
