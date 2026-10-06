import {useMemo, useState, type ReactNode} from 'react';
import {X} from 'lucide-react';
import type {LiveUsageDayDetail, LiveUsageTurnRow} from '@/lib/api/liveUsage';
import {cn} from '@/lib/utils';
import {
	NO_DATA,
	compactToken,
	costLabel,
	intLabel,
	rateLabel,
	shortModel,
	timeLabel,
	tokenLabel,
} from './labels';

/**
 * 某一天的会话明细（用量页下钻）：分会话表 + 分轮次可展开的"每枪一行"。
 *
 * 对齐 A3 网页报告的明细弹窗：搜索框按用户消息原文过滤、模型 chip 单选过滤、
 * 展开一轮看它每一次模型调用（重试 attempt 各占一行，与账本 S4 口径一致）。
 * 数据来自 `GET /v1/usage/report?day=`，不再依赖快照报告文件。
 */

function Th({children, num = false}: {children: ReactNode; num?: boolean}) {
	return (
		<th
			className={cn(
				'whitespace-nowrap px-3 py-1.5 font-normal text-mute',
				num ? 'text-right' : 'text-left',
			)}
		>
			{children}
		</th>
	);
}

function Td({children, num = false}: {children: ReactNode; num?: boolean}) {
	return (
		<td className={cn('px-3 py-1.5', num ? 'text-right tabular-nums' : 'text-left')}>
			{children}
		</td>
	);
}

export function TurnDrilldown({
	detail,
	loading,
	error,
	onClose,
}: {
	detail: LiveUsageDayDetail | null;
	loading: boolean;
	error: string;
	onClose: () => void;
}) {
	const [query, setQuery] = useState('');
	const [model, setModel] = useState('');
	const [open, setOpen] = useState<string | null>(null);

	const turns = detail?.turns ?? [];
	const models = useMemo(() => {
		const seen = new Map<string, string>();
		for (const t of turns) {
			if (t.model) seen.set(t.model, shortModel(t.model));
		}
		return [...seen.entries()];
	}, [turns]);

	const shown = useMemo(() => {
		const q = query.trim().toLowerCase();
		return turns
			.filter(t => (q ? (t.label ?? '').toLowerCase().includes(q) : true))
			.filter(t => (model ? t.model === model : true))
			.slice()
			.sort((a, b) => (b.first_ts ?? 0) - (a.first_ts ?? 0));
	}, [turns, query, model]);

	const summary = detail?.summary ?? null;
	const headText = loading
		? '正在读取这一天的明细…'
		: detail
			? `${detail.sessions.length} 个会话 · ${detail.turns.length} 轮 · 原始 events 只给到每枪一行`
			: error;

	return (
		<div className="xy-a3-drill border-t border-line bg-paper" data-a3-drill={detail?.day}>
			<div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
				<div className="min-w-0">
					<h3 className="text-[13px] font-medium text-ink">
						会话明细 · {detail?.day ?? ''}
					</h3>
					<p className="mt-0.5 text-[11px] text-mute">{headText}</p>
				</div>
				<button
					type="button"
					onClick={onClose}
					aria-label="收起会话明细"
					className="xy-icon-btn rounded-[var(--xy-radius-control)] p-1.5 text-mute hover:text-ink"
				>
					<X className="h-3.5 w-3.5" aria-hidden />
				</button>
			</div>

			{!detail && !loading ? (
				<p className="px-4 py-4 text-[12px] text-warn">{error}</p>
			) : detail ? (
				<div className="max-h-[520px] overflow-auto">
					{detail.missing ? (
						<p className="px-4 py-4 text-[12px] text-mute">
							账本可读，但这一天没有任何记录——这是"没跑"，不是"没读到"。
						</p>
					) : (
						<>
							<div className="flex flex-wrap items-center gap-2 px-4 py-2">
								<input
									type="search"
									value={query}
									onChange={e => setQuery(e.target.value)}
									aria-label="搜索用户消息"
									placeholder="搜索用户消息…"
									className="min-w-[180px] flex-1 rounded-[var(--xy-radius-control)] border border-line bg-paper px-2.5 py-1.5 text-[12px] text-ink outline-none placeholder:text-mute focus:border-accent/60"
								/>
								<div className="flex flex-wrap items-center gap-1">
									<Chip active={!model} onClick={() => setModel('')}>
										全部
									</Chip>
									{models.map(([id, label]) => (
										<Chip key={id} active={model === id} onClick={() => setModel(model === id ? '' : id)}>
											{label}
										</Chip>
									))}
								</div>
							</div>

							<h4 className="px-4 pb-1 text-[12px] font-medium text-ink-soft">
								按轮次（一条用户消息一行）
							</h4>
							{shown.length === 0 ? (
								<p className="px-4 py-3 text-[12px] text-mute">
									{turns.length === 0 ? '这一天没有轮次。' : '没有匹配的轮次。'}
								</p>
							) : (
								<ul className="px-4 pb-2">
									{shown.map(t => (
										<TurnRow
											key={`${t.session_id ?? ''}-${t.first_ts ?? ''}-${t.label ?? ''}`}
											turn={t}
											open={open === `${t.session_id}-${t.first_ts}-${t.label}`}
											onToggle={() =>
												setOpen(cur =>
													cur === `${t.session_id}-${t.first_ts}-${t.label}`
														? null
														: `${t.session_id}-${t.first_ts}-${t.label}`,
												)
											}
										/>
									))}
								</ul>
							)}

							<h4 className="border-t border-line px-4 pb-1 pt-3 text-[12px] font-medium text-ink-soft">
								按会话
							</h4>
							<div className="overflow-x-auto px-1 pb-3">
								<table className="w-full border-collapse text-[12px]">
									<thead className="sticky top-0 z-[1] border-y border-line bg-paper-deep">
										<tr>
											<Th>会话</Th>
											<Th num>命中率</Th>
											<Th num>请求</Th>
											<Th num>输入</Th>
											<Th num>输出</Th>
											<Th num>成本</Th>
										</tr>
									</thead>
									<tbody>
										{detail.sessions.map((s, i) => (
											<tr key={`${s.session_id ?? ''}-${i}`} className="border-b border-line/60">
												<Td>
													{s.session_id === '(none)' ? '未归类（账本没有会话归属）' : (s.session_id ?? NO_DATA)}
												</Td>
												<Td num>{rateLabel(s)}</Td>
												<Td num>{intLabel(s.requests)}</Td>
												<Td num>{tokenLabel(s.prompt_tokens)}</Td>
												<Td num>{tokenLabel(s.output)}</Td>
												<Td num>{costLabel(s.cost_cny, s.cost_unknown_requests)}</Td>
											</tr>
										))}
									</tbody>
								</table>
							</div>

							{summary?.unattributed_requests && summary.unattributed_requests > 0 ? (
								<p className="px-4 pb-3 text-[11px] text-mute">
									{`另有 ${intLabel(summary.unattributed_requests)} 笔账本记录没有会话归属（老版本没写 session_id），已单列在「未归类」一行，不猜归属。`}
								</p>
							) : null}
							{detail.events_truncated && detail.events_truncated > 0 ? (
								<p className="px-4 pb-3 text-[11px] text-warn">
									{`这一天枪数超过上界，${intLabel(detail.events_truncated)} 枪的原文行未下发（日合计与分模型/分会话仍是完整口径）。`}
								</p>
							) : null}
						</>
					)}
				</div>
			) : null}
		</div>
	);
}

function Chip({
	children,
	active,
	onClick,
}: {
	children: ReactNode;
	active: boolean;
	onClick: () => void;
}) {
	return (
		<button
			type="button"
			onClick={onClick}
			aria-pressed={active}
			className={cn(
				'xy-press rounded-full border px-2 py-0.5 text-[11px] transition-colors',
				active
					? 'border-accent/50 bg-accent-soft text-accent'
					: 'border-line text-mute hover:bg-glass-hover hover:text-ink',
			)}
		>
			{children}
		</button>
	);
}

function TurnRow({turn, open, onToggle}: {turn: LiveUsageTurnRow; open: boolean; onToggle: () => void}) {
	const events = turn.events ?? [];
	return (
		<li className="border-b border-line/60 last:border-b-0" data-a3-turn={turn.label}>
			<button
				type="button"
				onClick={onToggle}
				aria-expanded={open}
				className="flex w-full items-baseline justify-between gap-3 py-2 text-left"
			>
				<span className="min-w-0 flex-1 truncate text-[12px] text-ink" title={turn.label}>
					{turn.label || '未命名消息'}
				</span>
				<span className="flex shrink-0 items-baseline gap-2 text-[11px] tabular-nums text-mute">
					<span>{shortModel(turn.model)}</span>
					<span>{rateLabel(turn)}</span>
					<span>{`${intLabel(turn.requests)} 次`}</span>
					<span>{costLabel(turn.cost_cny, turn.cost_unknown_requests)}</span>
				</span>
			</button>
			{open ? (
				<div className="overflow-x-auto pb-2">
					<table className="w-full border-collapse text-[11px]">
						<thead>
							<tr className="border-y border-line bg-paper-deep">
								<Th>时间</Th>
								<Th>模型</Th>
								<Th num>命中率</Th>
								<Th num>命中/输入</Th>
								<Th num>请求</Th>
								<Th num>输出</Th>
								<Th num>成本</Th>
								<Th num>Prompt</Th>
							</tr>
						</thead>
						<tbody>
							<tr className="border-b border-line/60">
								<Td>{timeLabel(turn.first_ts)}</Td>
								<Td>{shortModel(turn.model)}</Td>
								<Td num>{rateLabel(turn)}</Td>
								<Td num>
									{turn.cache_hit == null || turn.cache_miss == null
										? NO_DATA
										: `${compactToken(turn.cache_hit)} / ${compactToken(turn.cache_hit + turn.cache_miss)}`}
								</Td>
								<Td num>{intLabel(turn.requests)}</Td>
								<Td num>{tokenLabel(turn.output)}</Td>
								<Td num>{costLabel(turn.cost_cny, turn.cost_unknown_requests)}</Td>
								<Td num>{tokenLabel(turn.prompt_tokens)}</Td>
							</tr>
							{events.map((e, i) => (
								<tr
									key={`${e.ts ?? ''}-${i}`}
									data-a3-event-row={`${turn.label}-${i}`}
									className="border-b border-line/40 opacity-[0.82]"
								>
									<Td>{timeLabel(e.ts)}</Td>
									<Td>{shortModel(e.model)}</Td>
									<Td num>
										{e.cache_hit == null || e.cache_miss == null
											? NO_DATA
											: rateLabel({cache_hit: e.cache_hit, cache_miss: e.cache_miss})}
									</Td>
									<Td num>
										{e.cache_hit == null || e.cache_miss == null
											? NO_DATA
											: `${compactToken(e.cache_hit)} / ${compactToken(e.cache_hit + e.cache_miss)}`}
									</Td>
									<Td num>
										{e.attempt && e.attempt > 1 ? `1（第 ${e.attempt} 次尝试）` : '1'}
									</Td>
									<Td num>{tokenLabel(e.output)}</Td>
									<Td num>{costLabel(e.cost_cny)}</Td>
									<Td num>{tokenLabel(e.prompt_tokens)}</Td>
								</tr>
							))}
							{turn.events_truncated && turn.events_truncated > 0 ? (
								<tr>
									<td colSpan={8} className="px-3 py-1.5 text-[11px] text-warn">
										{`另有 ${intLabel(turn.events_truncated)} 枪的原文行未下发（该轮合计仍是完整口径）。`}
									</td>
								</tr>
							) : null}
						</tbody>
					</table>
				</div>
			) : null}
		</li>
	);
}
