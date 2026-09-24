/**
 * ExperimentsView.tsx — 「实验」视图（设计 §7–§9）。
 *
 * 后端实验模块由并行工作流实现，字段未定：这里**不声明、不推断任何字段**，
 * 只把端点返回的 JSON 原样结构化呈现；非 2xx 一律降级为「实验层未就绪」。
 * A0 不发模型请求；A1/A2 的启动需要用户明确给配置，界面不代为授权付费。
 */
import {useCallback, useEffect, useState} from 'react';
import {Loader2, RefreshCw} from 'lucide-react';
import {
	cancelDiagExperiment,
	listDiagExperiments,
	planDiagExperiment,
	startDiagExperiment,
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

const MODES = [
	{key: 'A0', label: 'A0 静态差异与确定性重算', hint: '零模型调用'},
	{key: 'A1', label: 'A1 同检查点单次响应配对', hint: '两次模型调用，不执行工具'},
	{key: 'A2', label: 'A2 隔离环境真实任务配对', hint: '两臂独立进程 + verifier'},
] as const;

export function ExperimentsView({
	sessionId,
	turnId,
}: {
	sessionId: string;
	turnId: string;
}) {
	const [mode, setMode] = useState<(typeof MODES)[number]['key']>('A0');
	const [baseline, setBaseline] = useState('');
	const [candidate, setCandidate] = useState('');
	const [repeats, setRepeats] = useState(1);
	const [budget, setBudget] = useState('');
	const [busy, setBusy] = useState<'plan' | 'start' | 'list' | 'cancel' | ''>('');
	const [plan, setPlan] = useState<DiagRawResult | null>(null);
	const [started, setStarted] = useState<DiagRawResult | null>(null);
	const [list, setList] = useState<DiagRawResult | null>(null);
	const [message, setMessage] = useState('');

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

	const body = useCallback((): Record<string, unknown> | null => {
		const b = parseSide(baseline, '基线配置');
		if (!b) return null;
		const c = parseSide(candidate, '候选配置');
		if (!c) return null;
		return {
			mode,
			session_id: sessionId,
			turn_id: turnId,
			baseline: b,
			candidate: c,
			repeats,
			...(budget.trim() ? {budget_cny: Number(budget.trim())} : {}),
		};
	}, [baseline, budget, candidate, mode, repeats, sessionId, turnId]);

	const refreshList = useCallback(async () => {
		setBusy('list');
		setList(await listDiagExperiments());
		setBusy('');
	}, []);

	useEffect(() => {
		void refreshList();
	}, [refreshList]);

	const notReady = (r: DiagRawResult | null) => r !== null && r.ok === false;

	return (
		<div className="xy-dig-col">
			<Section title="实验层状态" hint="端点未实现时按原样降级，不伪造结果">
				{notReady(list) ? (
					<Notice tone="warn">
						实验层未就绪 —— 列表端点返回 {(list as {error: string}).error || DASH}
					</Notice>
				) : (
					<Badge tone="ok">实验端点可访问</Badge>
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
							onClick={() => setMode(m.key)}
							className={cn('xy-dig-mode', mode === m.key && 'is-on')}
						>
							<span className="xy-dig-mode-key">{m.key}</span>
							<span className="xy-dig-mode-label">{m.label}</span>
							<span className="xy-dig-mode-hint">{m.hint}</span>
						</button>
					))}
				</div>
				<div className="xy-dig-form">
					<label className="xy-dig-field">
						<span>基线配置（JSON）</span>
						<textarea
							className="xy-dig-textarea font-mono"
							value={baseline}
							placeholder='{"prompt_block":"..."}'
							onChange={e => setBaseline(e.target.value)}
						/>
					</label>
					<label className="xy-dig-field">
						<span>候选配置（JSON）</span>
						<textarea
							className="xy-dig-textarea font-mono"
							value={candidate}
							placeholder='{"prompt_block":"..."}'
							onChange={e => setCandidate(e.target.value)}
						/>
					</label>
					<div className="xy-dig-field-row">
						<label className="xy-dig-field">
							<span>repeat</span>
							<input
								type="number"
								min={1}
								max={20}
								className="xy-dig-input"
								value={repeats}
								onChange={e => setRepeats(Number(e.target.value) || 1)}
							/>
						</label>
						<label className="xy-dig-field">
							<span>预算上限（CNY）</span>
							<input
								type="text"
								inputMode="decimal"
								className="xy-dig-input"
								value={budget}
								placeholder="留空 = 不设上限（计划里会标出）"
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
							void planDiagExperiment(b).then(r => {
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
						onClick={() => {
							const b = body();
							if (!b) return;
							setBusy('start');
							setMessage('');
							void startDiagExperiment({...b, idempotency_key: newIdempotencyKey()}).then(r => {
								setStarted(r);
								setBusy('');
								void refreshList();
							});
						}}
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
				{message ? <Notice tone="fail">{message}</Notice> : null}
			</Section>

			{plan ? (
				<Section title="计划结果" hint="端点原文">
					{plan.ok ? <JsonView value={plan.data} /> : <Notice tone="warn">实验层未就绪 —— {plan.error}</Notice>}
				</Section>
			) : null}

			{started ? (
				<Section title="启动回执" hint="端点原文">
					{started.ok ? <JsonView value={started.data} /> : <Notice tone="warn">实验层未就绪 —— {started.error}</Notice>}
				</Section>
			) : null}

			{list && list.ok ? (
				<Section title="已有实验" hint="端点原文，字段不做解释">
					<JsonView value={list.data} />
					<div className="xy-dig-actions">
						{collectIds(list.data).map(id => (
							<button
								key={id}
								type="button"
								className="xy-dig-btn"
								disabled={busy !== ''}
								onClick={() => {
									setBusy('cancel');
									void cancelDiagExperiment(id).then(r => {
										setMessage(r.ok ? `已请求取消 ${id}` : `取消失败：${r.error}`);
										setBusy('');
										void refreshList();
									});
								}}
							>
								取消 {id}
							</button>
						))}
					</div>
				</Section>
			) : null}
		</div>
	);
}

/** 在未知结构里找形如 id/experiment_id 的字符串，仅用于给出取消入口。 */
function collectIds(value: unknown, out: string[] = []): string[] {
	if (!value || typeof value !== 'object') return out;
	if (Array.isArray(value)) {
		for (const v of value) collectIds(v, out);
		return out;
	}
	const o = value as Record<string, unknown>;
	for (const [k, v] of Object.entries(o)) {
		if ((k === 'experiment_id' || k === 'id') && typeof v === 'string' && v.trim()) {
			if (!out.includes(v)) out.push(v);
			continue;
		}
		collectIds(v, out);
	}
	return out;
}
