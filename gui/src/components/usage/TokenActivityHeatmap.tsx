import {useMemo, useState} from 'react';
import type {LiveUsageDay} from '@/lib/api/liveUsage';
import {formatMoney} from '@/lib/formatUsage';
import {cn} from '@/lib/utils';
import {
	ACTIVITY_WEEKS,
	buildActivityGrid,
	buildCumulative,
	formatChineseTokens,
	type ActivityCell,
	type ActivityView,
} from './activityHeatmap';

/**
 * Token 活动：近 53 周的日/周格阵 + 累计总量。
 *
 * 「今天」不读客户端时钟，而是取服务端 `generated_at` 的日期部分——账本的 `day`
 * 字段按北京时间落，客户端在别的时区就会把"今天"画错一格。
 *
 * 三种格子说三种话：有活动（按档着色）、账本里没有这一天（空格）、晚于今天（不画）。
 * 把「没跑」与「读不出」混成同一格，就是把零活动画成缺数据。
 */

const VIEWS: {key: ActivityView; label: string}[] = [
	{key: 'day', label: '每天'},
	{key: 'week', label: '每周'},
	{key: 'cumulative', label: '累计总量'},
];

const WEEKDAY_TICKS: Record<number, string> = {1: '一', 3: '三', 5: '五'};

const HEAT_VAR = ['--xy-heat-0', '--xy-heat-1', '--xy-heat-2', '--xy-heat-3', '--xy-heat-4'] as const;

function cellTitle(cell: ActivityCell): string {
	if (cell.future) return `${cell.label} · 还没到`;
	if (!cell.has_data) return `${cell.label} · 没有用量记录`;
	if (cell.value == null) return `${cell.label} · Token 数读不出来`;
	return `${cell.label} · ${formatChineseTokens(cell.value)} Token`;
}

function Tooltip({cell, x, y}: {cell: ActivityCell; x: number; y: number}) {
	const lines: string[] = [];
	if (cell.future) lines.push('这一天还没到');
	else if (!cell.has_data) lines.push('账本里没有这一天的记录');
	else {
		lines.push(`Token ${formatChineseTokens(cell.value)}`);
		if (cell.requests != null) lines.push(`${cell.requests.toLocaleString('en-US')} 次请求`);
		if (cell.days_with_data > 1) lines.push(`${cell.days_with_data} 天有活动`);
		if (cell.cost_cny != null) {
			lines.push(
				`成本 ${formatMoney(cell.cost_cny)}${
					cell.cost_unknown_requests && cell.cost_unknown_requests > 0 ? '（部分未知）' : ''
				}`,
			);
		} else if (cell.cost_unknown_requests && cell.cost_unknown_requests > 0) {
			lines.push('成本 无价目');
		}
	}
	return (
		<div
			data-a3-heat-tip
			role="tooltip"
			className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-[var(--xy-radius-control)] border border-line bg-glass-strong px-2 py-1 text-[11px] leading-4 text-ink shadow-[var(--xy-composer-shadow)]"
			style={{left: x, top: y}}
		>
			<div className="font-medium">{cell.label}</div>
			{lines.map(l => (
				<div key={l} className="text-mute">
					{l}
				</div>
			))}
		</div>
	);
}

function Cell({
	cell,
	size,
	onHover,
	onLeave,
	active,
}: {
	cell: ActivityCell;
	size: number;
	onHover: (cell: ActivityCell, el: HTMLElement) => void;
	onLeave: () => void;
	active: boolean;
}) {
	if (cell.future) {
		// 未来日：占位但不着色——画成空格会读成"这一天没跑"，那是假事实。
		return <span data-a3-heat-future={cell.start} style={{width: size, height: size}} />;
	}
	return (
		<span
			data-a3-heat={cell.start}
			data-a3-heat-level={cell.level}
			data-a3-heat-value={cell.value ?? ''}
			title={cellTitle(cell)}
			aria-label={cellTitle(cell)}
			onMouseEnter={e => onHover(cell, e.currentTarget)}
			onFocus={e => onHover(cell, e.currentTarget)}
			onMouseLeave={onLeave}
			onBlur={onLeave}
			className={cn(
				'rounded-[2px] outline-none ring-offset-1 transition-[box-shadow] focus-visible:ring-1 focus-visible:ring-[var(--xy-accent)]',
				active && 'ring-1 ring-[var(--xy-accent)]',
			)}
			style={{
				width: size,
				height: size,
				background: `var(${HEAT_VAR[cell.level]})`,
				// 有行但 tokens 读不出：给一圈虚线边，与"零活动"分开说。
				boxShadow: cell.value == null && cell.has_data ? 'inset 0 0 0 1px var(--xy-mute)' : undefined,
			}}
		/>
	);
}

export function TokenActivityHeatmap({
	days,
	generatedAt,
}: {
	days: LiveUsageDay[];
	/** 服务端聚合时刻（ISO，带偏移）；日期部分即"今天"。 */
	generatedAt: string;
}) {
	const [view, setView] = useState<ActivityView>('day');
	const [tip, setTip] = useState<{cell: ActivityCell; x: number; y: number} | null>(null);
	const today = useMemo(() => {
		const m = /^(\d{4}-\d{2}-\d{2})/.exec(generatedAt || '');
		return m ? m[1]! : '';
	}, [generatedAt]);

	const grid = useMemo(() => buildActivityGrid(days, view, today), [days, view, today]);
	const cumulative = useMemo(
		() => (view === 'cumulative' ? buildCumulative(days) : null),
		[days, view],
	);

	const showHover = (cell: ActivityCell, el: HTMLElement) => {
		const host = el.closest('[data-a3-heat-host]');
		if (!host) return;
		const a = el.getBoundingClientRect();
		const b = host.getBoundingClientRect();
		setTip({cell, x: a.left - b.left + a.width / 2, y: a.top - b.top - 4});
	};

	return (
		<section
			data-a3-heat-host
			className="xy-usage-heat relative px-4 py-3"
			onMouseLeave={() => setTip(null)}
		>
			<div className="flex flex-wrap items-baseline justify-between gap-2">
				<div className="min-w-0">
					<h3 className="text-[13px] font-medium text-ink">Token 活动</h3>
					<p className="mt-0.5 text-[11px] text-mute">
						{view === 'cumulative'
							? `累计 ${formatChineseTokens(cumulative?.total ?? 0)} Token · ${
									cumulative?.days_with_data ?? 0
								} 天有记录`
							: `近 ${ACTIVITY_WEEKS} 周 · 覆盖 ${grid.active_cells} ${
									view === 'week' ? '周' : '天'
								} · 合计 ${formatChineseTokens(grid.total)} Token`}
					</p>
				</div>
				<div className="flex shrink-0 items-center gap-1" role="tablist" aria-label="Token 活动口径">
					{VIEWS.map(v => (
						<button
							key={v.key}
							type="button"
							role="tab"
							aria-selected={view === v.key}
							onClick={() => setView(v.key)}
							className={cn(
								'xy-press rounded-[var(--xy-radius-control)] px-2 py-1 text-[11px] transition-colors',
								view === v.key
									? 'bg-accent-soft text-accent'
									: 'text-mute hover:bg-glass-hover hover:text-ink',
							)}
						>
							{v.label}
						</button>
					))}
				</div>
			</div>

			{view === 'cumulative' ? (
				cumulative && cumulative.points.length > 0 ? (
					<CumulativeChart
						points={cumulative.points}
						total={cumulative.total}
						daysWithoutTokens={cumulative.days_without_tokens}
					/>
				) : (
					<p className="py-8 text-center text-[12px] text-mute">
						账本里还没有可累加的 Token 记录。
					</p>
				)
			) : grid.columns.length === 0 ? (
				<p className="py-8 text-center text-[12px] text-mute">账本里还没有可分桶的日期。</p>
			) : (
				<div className="mt-3 overflow-x-auto pb-1">
					<div className="flex min-w-max gap-1">
						{/* 星期刻度：日视图 7 行、周视图 1 行；周视图不需要。 */}
						{view === 'day' ? (
							<div
								data-a3-heat-weekdays
								className="flex flex-col justify-between pt-[13px] text-[9px] leading-none text-mute"
								style={{height: 7 * 11 + 6 * 3}}
							>
								{[0, 1, 2, 3, 4, 5, 6].map(i => (
									<span key={i} style={{height: 11}} className="flex items-center">
										{WEEKDAY_TICKS[i] ?? ''}
									</span>
								))}
							</div>
						) : null}
						<div className="min-w-0">
							{/* 月份轴：与格阵同一列宽（每列 14px：11 格 + 3 缝）。 */}
							<div data-a3-heat-months className="flex gap-[3px] text-[9px] leading-none text-mute">
								{grid.columns.map((_, i) => {
									const label = grid.months.find(m => m.column === i)?.label ?? '';
									return (
										<span
											key={`m-${i}`}
											className="overflow-visible whitespace-nowrap"
											style={{width: view === 'week' ? undefined : 14, minWidth: view === 'week' ? 44 : undefined}}
										>
											{label}
										</span>
									);
								})}
							</div>
							<div
								data-a3-heat-grid
								role="img"
								aria-label={`Token 活动：${
									view === 'week' ? `${grid.columns.length} 周` : `${ACTIVITY_WEEKS} 周 × 7 天`
								}，合计 ${formatChineseTokens(grid.total)} Token`}
								className={cn(
									'mt-1 flex gap-[3px]',
									view === 'week' && 'flex-wrap',
								)}
							>
								{grid.columns.map((column, ci) => (
									<div key={`c-${ci}`} className="flex flex-col gap-[3px]">
										{column.map(cell => (
											<Cell
												key={cell.key}
												cell={cell}
												size={view === 'week' ? 13 : 11}
												active={tip?.cell.key === cell.key}
												onHover={showHover}
												onLeave={() => setTip(null)}
											/>
										))}
									</div>
								))}
							</div>
						</div>
					</div>
					<div className="mt-2 flex items-center justify-end gap-1 text-[10px] text-mute">
						<span>少</span>
						{HEAT_VAR.map(v => (
							<span
								key={v}
								className="h-[10px] w-[10px] rounded-[2px]"
								style={{background: `var(${v})`}}
							/>
						))}
						<span>多</span>
					</div>
				</div>
			)}

			{tip ? <Tooltip cell={tip.cell} x={tip.x} y={tip.y} /> : null}
		</section>
	);
}

/** 累计总量：一条从 0 涨到当前总量的折线（面积用 --xy-chart-fill）。 */
function CumulativeChart({
	points,
	total,
	daysWithoutTokens,
}: {
	points: {day: string; total: number}[];
	total: number;
	daysWithoutTokens: number;
}) {
	const W = 720;
	const H = 150;
	const PAD = 6;
	const n = points.length;
	const stepX = n > 1 ? (W - PAD * 2) / (n - 1) : 0;
	const path = points
		.map((p, i) => {
			const x = PAD + i * stepX;
			const y = H - PAD - (total > 0 ? (p.total / total) * (H - PAD * 2) : 0);
			return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
		})
		.join(' ');
	const area = `${path} L${(PAD + (n - 1) * stepX).toFixed(1)},${H - PAD} L${PAD},${H - PAD} Z`;
	const first = points[0]?.day ?? '';
	const last = points[points.length - 1]?.day ?? '';
	return (
		<div className="mt-3" data-a3-cumulative>
			<svg
				viewBox={`0 0 ${W} ${H}`}
				preserveAspectRatio="none"
				className="h-[150px] w-full"
				role="img"
				aria-label={`累计总量：${first} 到 ${last}，合计 ${formatChineseTokens(total)} Token`}
			>
				<path d={area} fill="var(--xy-chart-fill)" stroke="none" />
				<path
					d={path}
					fill="none"
					stroke="var(--xy-chart)"
					strokeWidth={1.5}
					vectorEffect="non-scaling-stroke"
				/>
			</svg>
			<div className="mt-1 flex items-baseline justify-between text-[10px] text-mute">
				<span>{first}</span>
				{daysWithoutTokens > 0 ? (
					<span>{`${daysWithoutTokens} 天没给 Token 数，未计入合计`}</span>
				) : null}
				<span className="tabular-nums text-ink-soft">{formatChineseTokens(total)}</span>
			</div>
		</div>
	);
}
