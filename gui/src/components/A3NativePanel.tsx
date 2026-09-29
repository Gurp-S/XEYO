import {Fragment, useEffect, useMemo, useRef, useState, type ReactNode} from 'react';
import {ChevronDown, ChevronRight, X} from 'lucide-react';
import {
	getMemoryReportDay,
	type A3ReportData,
	type A3ReportDayDetail,
	type A3ReportDaySummary,
} from '@/lib/api';
import {formatCacheHitPercent, formatMoney, formatTokenCount} from '@/lib/formatUsage';
import {computeUsageSegments, segmentWidths} from '@/lib/usageSegments';
import {cn} from '@/lib/utils';

/**
 * A3 日监控报告的原生视图（用量页）。
 *
 * 前身是用量页里的一个 iframe：那份 HTML 有 10 MB，其中 99.6 % 是生成器内嵌的
 * `window.__A3__` JSON（实测 10,587,777 / 10,629,939 字节，其中一半是 `total` 重嵌的
 * 同一份明细），于是界面只能贴整个网页——白底、不跟主题、看不出是本 app 的东西。
 * 这里改吃 `GET /v1/settings/memory/report/data`（同一份数据裁到 12 KB 左右），
 * 配色一律走 `var(--xy-*)`。命中/未命中的输入 token 构成用 `usageSegments` 的纯计算。
 * 小时分布不复用共享的 `UsageChart`：它把零高度的柱子直接不渲染、且 x 轴刻度点写死成
 * 四个索引，表达不出「24 小时都在标度上 + 零轮次的小时也占一格 + 固定 0/6/12/18/23 刻度」。
 * 为不动这个被多处共用的组件，这里在本面板内做一个只依赖 `var(--xy-*)` 的按小时槽位直方图。
 *
 * 口径说明（对齐报告本身的算法）：
 * - 命中率 = cache_hit / (cache_hit + cache_miss)，与网页 `pct(hit/(hit+miss))` 同式；
 * - 小时分布按**服务端本地小时**分桶（生成器 `hourOf(ts)` 用的也是渲染机本地小时）；
 * - 轮次明细的原始 `events` 数组不下发，只下发条数。
 */

/** 数据里没有这项时统一说的话——不猜、不用 0 顶、不静默画 dashes。 */
const NO_DATA = '数据里没有';

function intLabel(value?: number | null): string {
	return value == null ? NO_DATA : Math.round(value).toLocaleString('en-US');
}

function tokenLabel(value?: number | null): string {
	return value == null ? NO_DATA : formatTokenCount(value);
}

/** 紧凑 token，去掉 " tok" 单位——用在成对的「命中/输入」这种单位已在表头言明的格子里。 */
function compactToken(value?: number | null): string {
	return value == null ? NO_DATA : formatTokenCount(value).replace(/ tok$/, '');
}

/** 成本：统一走 `formatMoney`（≥¥1 两位、<¥1 四位）；0 是真值，不当缺失。 */
function costLabel(value?: number | null): string {
	return value == null || !Number.isFinite(value) ? NO_DATA : formatMoney(value);
}

/** 命中率优先用 hit/miss 两个分母算（与网页同式），两者都没有才退到 hit_rate 字段。 */
function rateLabel(day: {
	cache_hit?: number | null;
	cache_miss?: number | null;
	hit_rate?: number | null;
}): string {
	const oneDecimal =
		day.cache_hit != null && day.cache_miss != null
			? formatCacheHitPercent(day.cache_hit, day.cache_miss)
			: null;
	if (oneDecimal) return `${oneDecimal}%`;
	if (day.hit_rate != null) return `${(day.hit_rate * 100).toFixed(1)}%`;
	return NO_DATA;
}

function timeLabel(ts?: number | null): string {
	if (ts == null) return NO_DATA;
	const date = new Date(ts * 1000);
	return Number.isNaN(date.getTime()) ? NO_DATA : date.toTimeString().slice(0, 8);
}

function generatedLabel(iso: string): string {
	if (!iso) return NO_DATA;
	const date = new Date(iso);
	return Number.isNaN(date.getTime()) ? iso : date.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
}

function shortModel(model?: string): string {
	return (model || '').split('/').pop() || '未记模型';
}

/** KPI 单元：扁平一层；格线由网格 `gap-px` + 底色 `bg-line` 拼出，不套卡片。 */
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
		<div className="min-w-0 bg-paper px-4 py-3" data-a3-kpi={label}>
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
 * 报告的一天给的 `cache_hit` / `cache_miss` 就是**输入 token 的两半**（实测恒等于
 * `prompt_tokens`：23,971,930 + 2,300,223 = 26,272,153），与该模块回退分段的口径同形，
 * 所以复用它的分段与宽度算法；配色由模块给出，本来就是 `var(--xy-chart-*)` 令牌。
 * 两者都为 0 / 读不出时整条不渲染——宽度钳制有 0.5% 下限，画出来会是假的五五分。
 */
function InputCacheSplit({day}: {day: A3ReportDaySummary}) {
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
	);
}

function Td({children, num = false}: {children: ReactNode; num?: boolean}) {
	return (
		<td className={cn('px-3 py-1.5', num ? 'text-right tabular-nums' : 'text-left')}>
			{children}
		</td>
	);
}

/** 单位成本 = 当日成本 / 当日请求数；任一缺失就说缺失，不合成一个看起来像数的东西。 */
function perRequestLabel(day: A3ReportDaySummary): string {
	if (day.cost_cny == null || day.requests == null || day.requests <= 0) {
		return NO_DATA;
	}
	return formatMoney(day.cost_cny / day.requests);
}

/** 固定的 x 轴刻度小时（末点取 23 而非 24，保证「到 23:59 为止」这一档可读）。 */
const HOUR_TICKS = [0, 6, 12, 18, 23] as const;

/**
 * 请求 · 小时分布：固定 24 槽，小时即索引，零轮次的小时也在标度上占一格。
 *
 * 共享的 `UsageChart` 会跳过零高度柱子、且把 x 刻度写死成四个索引，做不到这点；
 * 为不动它，这里在本面板内用 `var(--xy-*)` 令牌画最简槽位图（柱子按小时定位，
 * 高度 = 该小时轮数 / 峰值；零小时给一根 3px 的 `--xy-line` 底桩占位）。
 */
function HourHistogram({day}: {day: A3ReportDaySummary}) {
	// 定长 24：越界/缺失补 0，杜绝「有几桶画几格」把柱子挤到左边。
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
				<h3 className="text-[13px] font-medium text-ink">请求 · 小时分布</h3>
				<p className="text-[11px] text-mute">
					{empty
						? '这一天的报告数据里没有可分桶的轮次时间戳'
						: '按轮次首次请求的服务端本地小时分桶' +
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

function ModelTable({day}: {day: A3ReportDaySummary}) {
	return (
		<div className="overflow-x-auto px-4 py-3">
			<h3 className="mb-2 text-[13px] font-medium text-ink">分模型</h3>
			{day.by_model.length === 0 ? (
				<p className="text-[12px] text-mute">这一天的报告数据里没有分模型行。</p>
			) : (
				<table className="w-full border-collapse text-[12px]">
				<thead>
					<tr className="border-y border-line bg-paper-deep">
						<Th>模型</Th>
						<Th>渠道</Th>
						<Th num>命中率</Th>
						<Th num>命中/输入</Th>
						<Th num>请求</Th>
						<Th num>输出</Th>
						<Th num>成本</Th>
					</tr>
				</thead>
				<tbody>
					{day.by_model.map((m, i) => (
						<tr
							key={`${m.provider ?? ''}/${m.model ?? ''}-${i}`}
							className="border-b border-line/60"
						>
							<Td>{shortModel(m.model)}</Td>
							<Td>{m.provider ?? NO_DATA}</Td>
							<Td num>{rateLabel(m)}</Td>
							<Td num>
								{m.cache_hit == null || m.cache_miss == null
									? NO_DATA
									: `${compactToken(m.cache_hit)} / ${compactToken((m.cache_hit ?? 0) + (m.cache_miss ?? 0))}`}
							</Td>
							<Td num>{intLabel(m.requests)}</Td>
							<Td num>{tokenLabel(m.output)}</Td>
							<Td num>{costLabel(m.cost_cny)}</Td>
						</tr>
					))}
				</tbody>
				</table>
			)}
		</div>
	);
}

/** 会话明细：一次 `?day=` 请求换一天，切日即失效重取。 */
function DayDetail({day, onClose}: {day: string; onClose: () => void}) {
	const [detail, setDetail] = useState<A3ReportDayDetail | null>(null);
	const [error, setError] = useState('');
	const [loading, setLoading] = useState(true);
	const requestRef = useRef(0);

	useEffect(() => {
		const requestId = ++requestRef.current;
		setDetail(null);
		setError('');
		setLoading(true);
		void getMemoryReportDay(day).then(r => {
			if (requestRef.current !== requestId) return;
			if (r.ok && r.data) setDetail(r.data);
			else setError(`没读到 ${day} 的会话明细（${r.message || 'unknown'}）`);
			setLoading(false);
		});
		return () => {
			requestRef.current += 1;
		};
	}, [day]);

	return (
		<div className="border-t border-line bg-paper">
			<div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
				<div className="min-w-0">
					<h3 className="text-[13px] font-medium text-ink">会话明细 · {day}</h3>
					<p className="mt-0.5 text-[11px] text-mute">
						{loading
							? '正在读取这一天的明细…'
							: detail
								? `${detail.sessions.length} 个会话 · ${detail.turns.length} 轮 · 原始 events 未下发，只给条数`
								: error}
					</p>
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
			{detail ? (
				<div className="max-h-[440px] overflow-auto">
					<h4 className="px-4 pb-1 pt-2 text-[12px] font-medium text-ink-soft">
						按轮次（一条用户消息一行）
					</h4>
					<table className="w-full border-collapse text-[12px]">
						<thead className="sticky top-0 z-[1] border-y border-line bg-paper-deep">
							<tr>
								<Th>时间</Th>
								<Th>会话</Th>
								<Th>模型</Th>
								<Th>消息</Th>
								<Th num>命中率</Th>
								<Th num>请求</Th>
								<Th num>输出</Th>
								<Th num>成本</Th>
								<Th num>枪数</Th>
							</tr>
						</thead>
						<tbody>
							{detail.turns.map((t, i) => (
								<tr key={`${t.session_id ?? ''}-${t.first_ts ?? ''}-${i}`} className="border-b border-line/60">
									<Td>{timeLabel(t.first_ts)}</Td>
									<Td>{t.session_id ?? NO_DATA}</Td>
									<Td>{shortModel(t.model)}</Td>
									<Td>
										<span className="line-clamp-1 text-ink-soft" title={t.label}>
											{t.label || '未命名消息'}
										</span>
									</Td>
									<Td num>{rateLabel(t)}</Td>
									<Td num>{intLabel(t.requests)}</Td>
									<Td num>{tokenLabel(t.output)}</Td>
									<Td num>{costLabel(t.cost_cny)}</Td>
									<Td num>{intLabel(t.event_count)}</Td>
								</tr>
							))}
						</tbody>
					</table>
					<h4 className="border-t border-line px-4 pb-1 pt-3 text-[12px] font-medium text-ink-soft">
						按会话
					</h4>
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
									<Td>{s.session_id ?? NO_DATA}</Td>
									<Td num>{rateLabel(s)}</Td>
									<Td num>{intLabel(s.requests)}</Td>
									<Td num>{tokenLabel(s.prompt_tokens)}</Td>
									<Td num>{tokenLabel(s.output)}</Td>
									<Td num>{costLabel(s.cost_cny)}</Td>
								</tr>
							))}
						</tbody>
					</table>
					{detail.turns.length === 0 && detail.sessions.length === 0 ? (
						<p className="px-4 py-4 text-[12px] text-mute">这一天没有任何会话行。</p>
					) : null}
				</div>
			) : loading ? null : (
				<p className="px-4 py-4 text-[12px] text-warn">{error}</p>
			)}
		</div>
	);
}

export function A3NativePanel({data}: {data: A3ReportData}) {
	const lastDay = data.days.length > 0 ? data.days[data.days.length - 1]!.day : '';
	const [selected, setSelected] = useState(lastDay);
	const [detailDay, setDetailDay] = useState<string | null>(null);

	// 刷新后日集合可能变（补齐历史天 / 新的一天）：选中日不在集合里就回到最后一天。
	useEffect(() => {
		if (!data.days.some(d => d.day === selected)) {
			setSelected(lastDay);
		}
	}, [data.days, lastDay, selected]);

	const day = data.days.find(d => d.day === selected) ?? data.days[data.days.length - 1];

	return (
		<div className="xy-a3-native">
			<div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
				<label className="flex items-center gap-2 text-[12px] text-ink-soft">
					日期
					<select
						value={selected}
						onChange={e => setSelected(e.target.value)}
						aria-label="选择查看的快照日期"
						className="rounded-[var(--xy-radius-control)] border border-line bg-paper px-2 py-1 text-[12px] text-ink"
					>
						{data.days.map(d => (
							<option key={d.day} value={d.day}>
								{d.day}
							</option>
						))}
					</select>
				</label>
				<p className="text-[11px] text-mute">
					{data.day_count} 天 · 生成于 {generatedLabel(data.generated_at)} · 快照状态：
					{day ? (day.accepted ? '已验收' : '待验收') : NO_DATA}
				</p>
			</div>

			{!day ? (
				<p className="px-4 py-8 text-center text-[12px] text-mute">
					报告里没有任何一天的数据。
				</p>
			) : (
				<>
					<div className="grid grid-cols-2 gap-px border-b border-line bg-line/40 md:grid-cols-4">
						<Kpi
							label="命中率"
							value={rateLabel(day)}
							extra={<InputCacheSplit day={day} />}
						/>
						<Kpi label="请求" value={intLabel(day.requests)} />
						<Kpi label="输出 token" value={tokenLabel(day.output)} />
						<Kpi label="输入 token" value={tokenLabel(day.prompt_tokens)} />
						<Kpi label="成本" value={costLabel(day.cost_cny)} />
						<Kpi label="C2" value={intLabel(day.c2_count)} />
						<Kpi label="会话数" value={intLabel(day.sessions)} />
						<Kpi label="单位成本" value={perRequestLabel(day)} />
					</div>

					<div className="border-b border-line">
						<HourHistogram day={day} />
					</div>

					<div className="border-b border-line">
						<ModelTable day={day} />
					</div>

					<div className="overflow-x-auto">
						<div className="flex items-baseline justify-between gap-2 px-4 pb-1 pt-3">
							<h3 className="text-[13px] font-medium text-ink">每日快照</h3>
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
											title={`${d.day}：切到这一天的报告`}
											className={cn(
												'cursor-pointer border-b border-line/60 hover:bg-paper-deep',
												d.day === day.day && 'bg-paper-deep',
											)}
										>
											<Td>{d.day}</Td>
											<Td>{d.accepted ? '已验收' : '待验收'}</Td>
											<Td num>{rateLabel(d)}</Td>
											<Td num>{intLabel(d.requests)}</Td>
											<Td num>{tokenLabel(d.prompt_tokens)}</Td>
											<Td num>{tokenLabel(d.output)}</Td>
											<Td num>{costLabel(d.cost_cny)}</Td>
											<Td num>{intLabel(d.c2_count)}</Td>
											<Td num>{intLabel(d.sessions)}</Td>
											<Td num>{intLabel(d.turns)}</Td>
										</tr>
									))}
							</tbody>
						</table>
					</div>

					<div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5">
						<button
							type="button"
							onClick={() => setDetailDay(detailDay ? null : day.day)}
							className="xy-press inline-flex items-center gap-1.5 rounded-[var(--xy-radius-control)] border border-line px-3 py-1.5 text-xs text-ink-soft transition-colors hover:border-accent/50 hover:bg-accent-soft hover:text-accent"
						>
							{detailDay ? (
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

					{detailDay ? <DayDetail day={detailDay} onClose={() => setDetailDay(null)} /> : null}
				</>
			)}
		</div>
	);
}
