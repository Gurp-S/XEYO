import {Fragment, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {ChevronDown, ChevronRight, Download} from 'lucide-react';
import {fetchLiveUsageDay, type LiveUsageDayDetail, type LiveUsageReport} from '@/lib/api';
import {DonutCard, type DonutSegment} from '@/components/usage/DonutCard';
import {ModelTable} from '@/components/usage/ModelTable';
import {TokenActivityHeatmap} from '@/components/usage/TokenActivityHeatmap';
import {TurnDrilldown} from '@/components/usage/TurnDrilldown';
import {downloadUsageJson} from '@/components/usage/exportUsageJson';
import {seriesColor} from '@/components/usage/palette';
import {
	NO_DATA,
	NO_PRICE,
	PARTIAL,
	costLabel,
	generatedLabel,
	intLabel,
	rateLabel,
	shortModel,
	snapshotLabel,
	tokenLabel,
} from '@/components/usage/labels';
import {formatMoney, formatTokenCount} from '@/lib/formatUsage';
import {computeUsageSegments, segmentWidths} from '@/lib/usageSegments';
import {toast} from '@/lib/toast';
import {cn} from '@/lib/utils';
import {A3DayNavigator} from './review/A3DayNavigator';

/**
 * 用量页的看板视图（数据来自 `GET /v1/usage/report`，即本机账本的实时聚合）。
 *
 * 演进：最早用量页贴 A3 报告的 10 MB 网页（iframe，白底、不跟主题）；R5 换成吃
 * `/report/data` 的原生视图，但那份数据仍是**快照**——不点「立即快照」，今天就是空的。
 * 现在改吃实时账本，快照降级成次要动作（生成网页报告 / 浏览器打开），界面与表D 各读
 * 各的源，但同一套口径（对账钉在 `python/tests/test_usage_live_report.py`）。
 *
 * 与网页报告的功能对齐：模型多选过滤、四张环形卡（命中率 / 输入构成 / 成本 / 请求
 * 分模型，弧与明细行互相高亮）、分模型对比条、会话明细里的"每枪一行" + 用户消息搜索 +
 * 模型 chip、导出 JSON。配色一律 `var(--xy-*)`（写死色由本文件的源码门扫）。
 *
 * 口径：
 * - 命中率 = cache_hit / (cache_hit + cache_miss)，与网页 `pct(hit/(hit+miss))` 同式；
 * - 小时分布按**轮次**首笔时间、北京时间分桶（与 `day` 字段同时区）；
 * - 环形卡/分模型表受多选过滤影响，KPI 与热力图始终是当天/全区间的完整口径——
 *   过滤是"看哪几个模型"，不是"重算这一天"。
 */

function Kpi({
	label,
	sub,
	value,
	extra,
}: {
	label: string;
	sub?: string;
	value: string;
	extra?: ReactNode;
}) {
	return (
		<div className="xy-a3-kpi min-w-0 bg-paper px-4 py-3" data-a3-kpi={label}>
			<div className="flex items-baseline gap-1.5">
				<span className="text-[12px] text-ink-soft">{label}</span>
				{sub ? <span className="text-[10px] tracking-wide text-mute">{sub}</span> : null}
			</div>
			<div className="mt-1 truncate text-[16px] tabular-nums text-ink" title={value}>
				{value}
			</div>
			{extra}
		</div>
	);
}

/**
 * 命中率下面那根构成条：直接吃 `usageSegments` 的纯计算，不另立图形原语。
 *
 * 一天的 `cache_hit` / `cache_miss` 就是**输入 token 的两半**（实测恒等于 prompt_tokens），
 * 与该模块回退分段的口径同形，所以复用它的分段与宽度算法；配色由模块给出，本来就是
 * `var(--xy-chart-*)` 令牌。两者都为 0 / 读不出时整条不渲染——宽度钳制有 0.5 % 下限，
 * 画出来会是假的五五分。
 */
function InputCacheSplit({day}: {day: LiveUsageReport['days'][number]}) {
	const {segments, denominator} = useMemo(
		() =>
			computeUsageSegments({
				contextBreakdown: null,
				lastCacheHitTokens: day.cache_hit ?? null,
				lastCacheMissTokens: day.cache_miss ?? null,
			}),
		[day.cache_hit, day.cache_miss],
	);
	const sum = segments.reduce((acc, s) => acc + s.tokens, 0);
	if (sum <= 0) return null;
	const widths = segmentWidths(segments, denominator);
	return (
		<div
			className="mt-2"
			data-a3-hitmiss
			role="img"
			aria-label={segments.map(s => `${s.label} ${formatTokenCount(s.tokens)}`).join(' · ')}
		>
			<div className="flex h-1 w-full overflow-hidden rounded-full bg-glass">
				{segments.map((s, i) => (
					<span
						key={s.key}
						title={`${s.label} · ${formatTokenCount(s.tokens)}`}
						className="h-full"
						style={{width: `${widths[i] ?? 0}%`, background: s.color}}
					/>
				))}
			</div>
			<div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
				{segments.map((s, i) => (
					<Fragment key={`t-${s.key}`}>
						{i > 0 ? (
							<span aria-hidden className="text-[10px] text-mute">
								·
							</span>
						) : null}
						<span className="text-[10px] text-mute">
							{s.label} {formatTokenCount(s.tokens)}
						</span>
					</Fragment>
				))}
			</div>
		</div>
	);
}

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
	)
}

function Td({children, num = false}: {children: ReactNode; num?: boolean}) {
	return (
		<td className={cn('px-3 py-1.5', num ? 'text-right tabular-nums' : 'text-left')}>{children}</td>
	);
}

/** 单位成本 = 当日成本 / 当日请求数；缺价目/缺请求数就说缺失，不合成一个看起来像数的东西。 */
function perRequestLabel(day: LiveUsageReport['days'][number]): string {
	if (day.cost_cny === null) return NO_PRICE;
	if (day.cost_cny == null || day.requests == null || day.requests <= 0) return NO_DATA;
	const money = formatMoney(day.cost_cny / day.requests);
	return day.cost_unknown_requests != null && day.cost_unknown_requests > 0
		? `${money}（${PARTIAL}）`
		: money;
}

/** 固定的 x 轴刻度小时（末点取 23 而非 24，保证「到 23:59 为止」这一档可读）。 */
const HOUR_TICKS = [0, 6, 12, 18, 23] as const;

/**
 * 请求活动：固定 24 槽，小时即索引，零轮次的小时也在标度上占一格。
 *
 * 共享的 `UsageChart` 会跳过零高度柱子、且把 x 刻度写死成四个索引，做不到这点；
 * 为不动它，这里在本面板内用 `var(--xy-*)` 令牌画最简槽位图。
 */
function HourHistogram({day}: {day: LiveUsageReport['days'][number]}) {
	const slots = useMemo(
		() =>
			Array.from({length: 24}, (_, hour) => {
				const raw = day.hour_counts[hour];
				return {hour, count: typeof raw === 'number' && raw > 0 ? raw : 0};
			}),
		[day.hour_counts],
	);
	const max = slots.reduce((m, s) => Math.max(m, s.count), 0);
	const empty = max === 0;
	return (
		<div className="px-4 py-3">
			<div className="flex flex-wrap items-baseline justify-between gap-2">
				<h3 className="text-[13px] font-medium text-ink">活动分布 · 每小时轮次</h3>
				<p className="text-[11px] text-mute">
					{empty
						? '这一天没有可分桶的轮次时间戳'
						: '0—23 点 · 北京时间' +
							(day.hour_unknown > 0 ? `；${day.hour_unknown} 轮无时间戳，未计入` : '')}
				</p>
			</div>

			<div
				data-a3-hour-chart
				role="img"
				aria-label={
					empty
						? '小时分布：这一天没有任何轮次'
						: `小时分布：0—23 点共 24 格，峰值 ${max} 轮/小时`
				}
				className="mt-3 flex items-end gap-px"
				style={{height: 132}}
			>
				{slots.map(s => (
					<div
						key={`h-${s.hour}`}
						data-a3-hour={s.hour}
						data-a3-hour-count={s.count}
						title={`${String(s.hour).padStart(2, '0')}:00 · ${s.count} 轮`}
						className="flex min-w-0 flex-1 items-end"
						style={{height: '100%'}}
					>
						<div
							className="w-full rounded-t-[2px]"
							style={{
								height: s.count > 0 ? `${(s.count / max) * 100}%` : '3px',
								background: s.count > 0 ? 'var(--xy-chart)' : 'var(--xy-line)',
							}}
						/>
					</div>
				))}
			</div>

			<div data-a3-hour-axis className="mt-1 flex gap-px text-[10px] text-mute">
				{slots.map(s => (
					<div key={`t-${s.hour}`} className="min-w-0 flex-1 text-center">
						{HOUR_TICKS.includes(s.hour as (typeof HOUR_TICKS)[number]) ? (
							<span className="tabular-nums">{s.hour}</span>
						) : null}
					</div>
				))}
			</div>
		</div>
	);
}

/** 会话明细：一次 `?day=` 请求换一天，切日即失效重取。 */
function useDayDetail(selectedDay: string | undefined, wanted: boolean) {
	const [detail, setDetail] = useState<LiveUsageDayDetail | null>(null);
	const [error, setError] = useState('');
	const [loading, setLoading] = useState(false);
	const requestRef = useRef(0);

	useEffect(() => {
		if (!wanted || !selectedDay) return;
		const requestId = ++requestRef.current;
		setLoading(true);
		setError('');
		void fetchLiveUsageDay(selectedDay)
			.then(r => {
				if (requestRef.current !== requestId) return;
				if (r.ok && r.data) setDetail(r.data);
				else {
					setDetail(null);
					setError(`没读到 ${selectedDay} 的会话明细（${r.message || 'unknown'}）`);
				}
			})
			.catch(error => {
				if (requestRef.current !== requestId) return;
				setError(error instanceof Error ? error.message : '读取会话明细失败');
			})
			.finally(() => {
				if (requestRef.current === requestId) setLoading(false);
			});
		return () => {
			requestRef.current += 1;
		};
	}, [selectedDay, wanted]);

	// 切日即作废：留着上一天的明细会让"这一天的会话数"读成假值。
	useEffect(() => {
		setDetail(null);
		setError('');
	}, [selectedDay]);

	return {detail, error, loading};
}

export function A3NativePanel({data}: {data: LiveUsageReport}) {
	const lastDay = data.days.length > 0 ? data.days[data.days.length - 1]!.day : '';
	const [selected, setSelected] = useState(lastDay);
	const [detailOpen, setDetailOpen] = useState(false);
	const [picked, setPicked] = useState<string[]>([]);

	// 刷新后日集合可能变（新的一天 / 账本补齐历史天）：选中日不在集合里就回到最后一天。
	useEffect(() => {
		if (!data.days.some(d => d.day === selected)) setSelected(lastDay);
	}, [data.days, lastDay, selected]);

	const day = data.days.find(d => d.day === selected) ?? data.days[data.days.length - 1];
	const allModels = day?.by_model ?? [];
	const colorIndex = useMemo(() => {
		const map = new Map<string, number>();
		allModels.forEach((m, i) => map.set(m.model ?? '', i));
		return map;
	}, [allModels]);
	const colorOf = (model: string) => seriesColor(colorIndex.get(model) ?? 0);
	const shownModels = picked.length
		? allModels.filter(m => picked.includes(m.model ?? ''))
		: allModels;

	// 多选过滤只影响环形卡与分模型表；切日时清掉，避免"选中的模型今天没有"的空图。
	useEffect(() => {
		setPicked([]);
	}, [selected]);

	const {detail, error: detailError, loading: detailLoading} = useDayDetail(day?.day, detailOpen);

	const seg = (model: string): DonutSegment['color'] => colorOf(model);
	const hitSegments: DonutSegment[] = shownModels.map(m => {
		const hit = m.cache_hit ?? 0;
		const miss = m.cache_miss ?? 0;
		const rate = hit + miss > 0 ? ((hit / (hit + miss)) * 100).toFixed(1) : '0.0';
		return {
			key: `hit-${m.model}`,
			label: shortModel(m.model),
			value: hit,
			color: seg(m.model ?? ''),
			percent: `${rate}%`,
			valueLabel: `${formatTokenCount(hit)} / ${formatTokenCount(hit + miss)}`,
		};
	});
	const inputSegments: DonutSegment[] = shownModels.map(m => ({
		key: `in-${m.model}`,
		label: m.model ?? '未记模型',
		value: m.prompt_tokens ?? null,
		color: seg(m.model ?? ''),
	}));
	const costSegments: DonutSegment[] = shownModels.map(m => ({
		key: `cost-${m.model}`,
		label: m.model ?? '未记模型',
		value: m.cost_cny ?? null,
		color: seg(m.model ?? ''),
		valueLabel: costLabel(m.cost_cny, m.cost_unknown_requests),
	}));
	const reqSegments: DonutSegment[] = shownModels.map(m => ({
		key: `req-${m.model}`,
		label: m.model ?? '未记模型',
		value: m.requests ?? null,
		color: seg(m.model ?? ''),
	}));

	const exportNow = () => {
		try {
			const name = downloadUsageJson(
				{source: 'live_ledger', generated_at: data.generated_at, report: data, day_detail: detail},
				data.generated_at,
			);
			toast.success(`已导出 ${name}`);
		} catch (err) {
			toast.error(err instanceof Error ? err.message : '导出失败');
		}
	};

	return (
		<div className="xy-a3-native xy-a3-dashboard">
			<A3DayNavigator
				days={data.days.map(d => ({day: d.day, requests: d.requests}))}
				selected={selected}
				onSelect={setSelected}
			/>
			<div className="xy-a3-body">
				<div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
					<div className="xy-a3-heading">
						<h2>{day?.day ?? '用量概览'}</h2>
						<p>费用、Token 与请求活动 · 本机账本实时</p>
					</div>
					<label className="xy-a3-date-select flex items-center gap-2 text-[12px] text-ink-soft">
						日期
						<select
							value={selected}
							onChange={e => setSelected(e.target.value)}
							aria-label="选择查看的日期"
							className="rounded-[var(--xy-radius-control)] border border-line bg-paper px-2 py-1 text-[12px] text-ink"
						>
							{data.days.map(d => (
								<option key={d.day} value={d.day}>
									{d.day}
								</option>
							))}
						</select>
					</label>
					<div className="flex shrink-0 items-center gap-2">
						<p className="text-[11px] text-mute">
							{data.day_count} 天 · 聚合于 {generatedLabel(data.generated_at)} · 快照状态：
							{day ? snapshotLabel(day.accepted) : NO_DATA}
						</p>
						<button
							type="button"
							onClick={exportNow}
							disabled={!data.days.length}
							className="xy-press inline-flex items-center gap-1.5 rounded-[var(--xy-radius-control)] border border-line/70 px-2.5 py-1 text-[11px] text-ink-soft transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-accent disabled:opacity-50"
						>
							<Download className="h-3.5 w-3.5" aria-hidden />
							导出 JSON
						</button>
					</div>
				</div>

				{!day ? (
					<p className="px-4 py-8 text-center text-[12px] text-mute">
						账本里还没有任何一天的数据。
					</p>
				) : (
					<>
						<div className="xy-a3-kpis grid grid-cols-2 gap-px border-b border-line bg-line/40 md:grid-cols-4">
							<Kpi label="成本" sub="当日已计价费用" value={costLabel(day.cost_cny, day.cost_unknown_requests)} />
							<Kpi
								label="命中率"
								sub="输入缓存复用"
								value={rateLabel(day)}
								extra={<InputCacheSplit day={day} />}
							/>
							<Kpi label="输入 token" sub="发送给模型" value={tokenLabel(day.prompt_tokens)} />
							<Kpi label="输出 token" sub="模型生成" value={tokenLabel(day.output)} />
							<Kpi label="请求" sub="模型调用次数" value={intLabel(day.requests)} />
							<Kpi label="单位成本" sub="每次请求平均" value={perRequestLabel(day)} />
							<Kpi label="会话数" sub="当日会话" value={intLabel(day.sessions)} />
							<Kpi label="轮次" sub="任务交互轮次" value={intLabel(day.turns)} />
						</div>

						<div className="border-b border-line">
							<TokenActivityHeatmap days={data.days} generatedAt={data.generated_at} />
						</div>

						<div className="xy-a3-donuts grid grid-cols-1 gap-px border-b border-line bg-line/40 lg:grid-cols-2">
							<DonutCard
								title="整体命中率"
								sub="按模型 · 弧长=命中 token"
								segments={hitSegments}
								centerValue={rateLabel(day)}
								centerLabel="命中 / 总输入"
								emptyHint="这一天没有可分段的命中数据（未命中或读不出）。"
							/>
							<DonutCard
								title="输入 token · 构成"
								sub="按模型"
								segments={inputSegments}
								centerValue={tokenLabel(day.prompt_tokens)}
								centerLabel="总输入 token"
							/>
							<DonutCard
								title="成本 · 模型"
								sub="账本计价口径"
								segments={costSegments}
								centerValue={costLabel(day.cost_cny, day.cost_unknown_requests)}
								centerLabel="总成本 CNY"
								emptyHint="这一天没有已计价的行（无价目不等于免费）。"
							/>
							<DonutCard
								title="请求 · 模型"
								sub="模型调用次数"
								segments={reqSegments}
								centerValue={intLabel(day.requests)}
								centerLabel="总请求数"
							/>
						</div>

						<div className="xy-a3-filters flex flex-wrap items-center gap-1.5 border-b border-line px-4 py-2.5">
							<span className="text-[11px] text-mute">模型过滤</span>
							<button
								type="button"
								aria-pressed={picked.length === 0}
								onClick={() => setPicked([])}
								className={cn(
									'xy-press rounded-full border px-2 py-0.5 text-[11px] transition-colors',
									picked.length === 0
										? 'border-accent/50 bg-accent-soft text-accent'
										: 'border-line text-mute hover:bg-glass-hover hover:text-ink',
								)}
							>
								全部
							</button>
							{allModels.map(m => {
								const id = m.model ?? '';
								const on = picked.includes(id);
								return (
									<button
										key={id}
										type="button"
										aria-pressed={on}
										onClick={() =>
											setPicked(cur => (cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]))
										}
										className={cn(
											'xy-press inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] transition-colors',
											on
												? 'border-accent/50 bg-accent-soft text-accent'
												: 'border-line text-mute hover:bg-glass-hover hover:text-ink',
										)}
									>
										<span aria-hidden className="h-2 w-2 rounded-[2px]" style={{background: colorOf(id)}} />
										{id.split('/').pop() || '未记模型'}
										<span className="tabular-nums">{rateLabel(m)}</span>
									</button>
								);
							})}
							{picked.length ? (
								<span className="text-[11px] text-mute">
									只影响环形卡与分模型表；KPI 与热力图仍是这一天的完整口径。
								</span>
							) : null}
						</div>

						<div className="border-b border-line">
							<HourHistogram day={day} />
						</div>

						<div className="border-b border-line">
							<h3 className="px-4 pt-3 text-[13px] font-medium text-ink">分模型</h3>
							<ModelTable rows={shownModels} colorOf={colorOf} />
						</div>

						<details className="xy-a3-history">
							<summary>
								历史快照与运行记录
								<ChevronDown size={14} />
							</summary>
							<p className="xy-a3-c2">C2 事件：{intLabel(day.c2_count)}</p>
							<div className="overflow-x-auto">
								<div className="flex items-baseline justify-between gap-2 px-4 pb-1 pt-3">
									<h3 className="text-[13px] font-medium text-ink">每日记录</h3>
									<p className="text-[11px] text-mute">点一行切换上面的日期</p>
								</div>
								<table className="w-full border-collapse text-[12px]">
									<thead>
										<tr className="border-y border-line bg-paper-deep">
											<Th>日期</Th>
											<Th>状态</Th>
											<Th num>命中率</Th>
											<Th num>请求</Th>
											<Th num>输入</Th>
											<Th num>输出</Th>
											<Th num>成本</Th>
											<Th num>C2</Th>
											<Th num>会话</Th>
											<Th num>轮次</Th>
										</tr>
									</thead>
									<tbody>
										{data.days
											.slice()
											.reverse()
											.map(d => (
												<tr
													key={d.day}
													onClick={() => setSelected(d.day)}
													title={`${d.day}：切到这一天`}
													className={cn(
														'cursor-pointer border-b border-line/60 hover:bg-paper-deep',
														d.day === day.day && 'bg-paper-deep',
													)}
												>
													<Td>{d.day}</Td>
													<Td>{snapshotLabel(d.accepted)}</Td>
													<Td num>{rateLabel(d)}</Td>
													<Td num>{intLabel(d.requests)}</Td>
													<Td num>{tokenLabel(d.prompt_tokens)}</Td>
													<Td num>{tokenLabel(d.output)}</Td>
													<Td num>{costLabel(d.cost_cny, d.cost_unknown_requests)}</Td>
													<Td num>{intLabel(d.c2_count)}</Td>
													<Td num>{intLabel(d.sessions)}</Td>
													<Td num>{intLabel(d.turns)}</Td>
												</tr>
											))}
									</tbody>
								</table>
							</div>
						</details>

						<div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5">
							<button
								type="button"
								onClick={() => setDetailOpen(v => !v)}
								aria-expanded={detailOpen}
								className="xy-press inline-flex items-center gap-1.5 rounded-[var(--xy-radius-control)] border border-line px-3 py-1.5 text-xs text-ink-soft transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-accent"
							>
								{detailOpen ? (
									<ChevronDown className="h-3.5 w-3.5" aria-hidden />
								) : (
									<ChevronRight className="h-3.5 w-3.5" aria-hidden />
								)}
								查看会话明细
							</button>
							<p className="text-[11px] text-mute">
								成本按账本计价口径，与厂商账单可能有差；命中率分母 = 命中 + 未命中。
							</p>
						</div>

						{detailOpen ? (
							<TurnDrilldown
								detail={detail}
								loading={detailLoading}
								error={detailError}
								onClose={() => setDetailOpen(false)}
							/>
						) : null}
					</>
				)}
			</div>
		</div>
	);
}
