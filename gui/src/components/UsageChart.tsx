import {useEffect, useId, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {cn} from '@/lib/utils';

export type ChartKind = 'bar' | 'line';

export type ChartSeries = {
	key: string;
	label: string;
	color: string;
};

export type ChartRow = {
	label: string;
	date: string;
	values: Record<string, number>;
};

type Props = {
	rows: ChartRow[];
	series: ChartSeries[];
	kind: ChartKind;
	stacked?: boolean;
	height?: number;
	formatY?: (n: number) => string;
	formatTotal?: (n: number) => string;
	/**
	 * v4（B1）：命中/未命中/输出 三桶 disjoint，禁止相加成「总消耗」。
	 * 传入后 tooltip 顶行改用本函数逐项渲染，而不是显示系列之和。
	 */
	tipSummary?: (values: Record<string, number>) => string;
	emptyText?: string;
	className?: string;
};

function niceMax(raw: number): number {
	if (raw <= 0) {
		return 1;
	}
	const exp = Math.floor(Math.log10(raw));
	const base = 10 ** exp;
	const n = raw / base;
	const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
	return nice * base;
}

function ticks(max: number): number[] {
	return [0, max / 2, max];
}

function polyline(pts: {x: number; y: number}[]): string {
	if (pts.length === 0) {
		return '';
	}
	return pts
		.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
		.join(' ');
}

function barRadius(width: number, height: number): number {
	return Math.min(4, width / 2, Math.max(height / 2, 0));
}

export function UsageChart({
	rows,
	series,
	kind,
	stacked = false,
	height = 176,
	formatY = n => String(Math.round(n)),
	formatTotal,
	tipSummary,
	emptyText = '暂无数据',
	className,
}: Props) {
	const wrapRef = useRef<HTMLDivElement>(null);
	const [w, setW] = useState(640);
	const [hover, setHover] = useState<number | null>(null);
	const gid = useId().replace(/:/g, '');
	const pad = {l: 44, r: 16, t: 16, b: 28};
	const innerW = Math.max(40, w - pad.l - pad.r);
	const innerH = height - pad.t - pad.b;

	useEffect(() => {
		const el = wrapRef.current;
		if (!el) {
			return;
		}
			const apply = () => {
				const next = Math.max(240, el.clientWidth);
				setW(prev => (prev === next ? prev : next));
			};
			apply();
		const ro = new ResizeObserver(apply);
		ro.observe(el);
		return () => ro.disconnect();
	}, []);

	const totals = useMemo(
		() =>
			rows.map(row =>
				series.reduce((s, ser) => s + (row.values[ser.key] ?? 0), 0),
			),
		[rows, series],
	);
	const maxY = useMemo(() => niceMax(Math.max(0, ...totals)), [totals]);
	const yTicks = ticks(maxY);

	const xOf = (i: number) => {
		if (rows.length <= 1) {
			return pad.l + innerW / 2;
		}
		return pad.l + (i / (rows.length - 1)) * innerW;
	};
	const yOf = (v: number) =>
		pad.t + innerH - (Math.max(0, v) / maxY) * innerH;
	const slot = innerW / Math.max(rows.length, 1);
	const barW = Math.max(3, Math.min(22, slot * 0.4));

	const xLabels = useMemo(() => {
		if (rows.length <= 6) {
			return rows.map((r, i) => ({i, label: r.label}));
		}
		const last = rows.length - 1;
		const picks = [0, Math.round(last / 3), Math.round((last * 2) / 3), last];
		const seen = new Set<number>();
		return picks
			.filter(i => {
				if (seen.has(i)) {
					return false;
				}
				seen.add(i);
				return true;
			})
			.map(i => ({i, label: rows[i].label}));
	}, [rows]);

	const hasData = totals.some(n => n > 0);
	const hi = hover ?? -1;
	const dotR = rows.length >= 60 ? 1 : rows.length >= 30 ? 1.25 : 1.6;
	const dotHoverR = dotR + 0.9;
	const tipRef = useRef<HTMLDivElement>(null);
	const [tipBox, setTipBox] = useState({w: 176, h: 96});
	const tip = hi >= 0 && hi < rows.length ? rows[hi] : null;
	const tipTotal = hi >= 0 ? totals[hi] ?? 0 : 0;

	useLayoutEffect(() => {
		const el = tipRef.current;
		if (!el || !tip) {
			return;
		}
			const next = {w: el.offsetWidth, h: el.offsetHeight};
			setTipBox(prev =>
				prev.w === next.w && prev.h === next.h ? prev : next,
			);
	}, [tip, hi, series.length]);

	return (
		<div ref={wrapRef} className={cn('relative w-full', className)} style={{height}}>
			<svg
				width={w}
				height={height}
				viewBox={`0 0 ${w} ${height}`}
				className="overflow-visible"
				onMouseLeave={() => setHover(null)}
				onMouseMove={e => {
					const rect = e.currentTarget.getBoundingClientRect();
					const x = ((e.clientX - rect.left) / rect.width) * w;
					if (rows.length === 0) {
						return;
					}
					let best = 0;
					let bestD = Infinity;
					for (let i = 0; i < rows.length; i++) {
						const d = Math.abs(xOf(i) - x);
						if (d < bestD) {
							bestD = d;
							best = i;
						}
					}
					setHover(prev => (prev === best ? prev : best));
				}}
			>
				<defs>
					<linearGradient id={`${gid}-bar`} x1="0" y1="0" x2="0" y2="1">
						<stop offset="0%" stopColor="var(--xy-chart-mid)" />
						<stop offset="100%" stopColor="var(--xy-chart)" />
					</linearGradient>
					{hasData && kind === 'bar'
						? rows.map((row, i) => {
								const total = totals[i] ?? 0;
								const h = (total / maxY) * innerH;
								if (h <= 0) {
									return null;
								}
								const x = xOf(i) - barW / 2;
								const r = barRadius(barW, h);
								return (
									<clipPath key={row.date} id={`${gid}-barclip-${i}`}>
										<rect
											x={x}
											y={yOf(total)}
											width={barW}
											height={Math.max(h, 0.8)}
											rx={r}
											ry={r}
										/>
									</clipPath>
								);
							})
						: null}
				</defs>
				{yTicks.map(t => (
					<g key={t}>
						{t > 0 ? (
							<line
								x1={pad.l}
								x2={w - pad.r}
								y1={yOf(t)}
								y2={yOf(t)}
								stroke="var(--xy-line)"
								strokeOpacity={0.7}
								strokeDasharray="4 4"
								strokeWidth={1}
							/>
						) : null}
						<text
							x={pad.l - 8}
							y={yOf(t) + 3.5}
							textAnchor="end"
							fill="var(--xy-mute)"
							fontSize="11"
							fontFamily="ui-sans-serif, system-ui, sans-serif"
						>
							{formatY(t)}
						</text>
					</g>
				))}
				{xLabels.map(t => (
					<text
						key={t.i}
						x={xOf(t.i)}
						y={height - 8}
						textAnchor="middle"
						fill="var(--xy-mute)"
						fontSize="11"
						fontFamily="ui-sans-serif, system-ui, sans-serif"
					>
						{t.label}
					</text>
				))}

				{hasData && kind === 'bar'
					? rows.map((row, i) => {
							const x = xOf(i) - barW / 2;
							if (stacked || series.length === 1) {
								let acc = 0;
								return (
									<g key={row.date} clipPath={`url(#${gid}-barclip-${i})`}>
										{series.map(ser => {
											const v = row.values[ser.key] ?? 0;
											const h = (v / maxY) * innerH;
											const y = yOf(acc + v);
											acc += v;
											if (h <= 0) {
												return null;
											}
											return (
												<rect
													key={ser.key}
													x={x}
													y={y}
													width={barW}
													height={Math.max(h, 0.8)}
													fill={
														series.length === 1
															? `url(#${gid}-bar)`
															: ser.color
													}
													opacity={hi < 0 || hi === i ? 1 : 0.4}
												/>
											);
										})}
									</g>
								);
							}
							const inner = barW / series.length;
							return (
								<g key={row.date}>
									{series.map((ser, si) => {
										const v = row.values[ser.key] ?? 0;
										const h = (v / maxY) * innerH;
										if (h <= 0) {
											return null;
										}
										const bw = Math.max(inner - 0.6, 1.5);
										const r = barRadius(bw, h);
										return (
											<rect
												key={ser.key}
												x={x + si * inner}
												y={yOf(v)}
												width={bw}
												height={Math.max(h, 0.8)}
												rx={r}
												ry={r}
												fill={ser.color}
												opacity={hi < 0 || hi === i ? 1 : 0.4}
											/>
										);
									})}
								</g>
							);
						})
					: null}

				{hasData && kind === 'line'
					? series.map(ser => {
							const pts = rows.map((row, i) => ({
								x: xOf(i),
								y: yOf(row.values[ser.key] ?? 0),
								v: row.values[ser.key] ?? 0,
							}));
							if (pts.every(p => p.v <= 0)) {
								return null;
							}
							const line = polyline(pts);
							return (
								<g key={ser.key}>
									<path
										d={line}
										fill="none"
										stroke={ser.color}
										strokeWidth={1.75}
										strokeLinejoin="round"
										strokeLinecap="round"
									/>
									{pts.map((p, i) => (
										<circle
											key={`${ser.key}-${i}`}
											cx={p.x}
											cy={p.y}
											r={hi === i ? dotHoverR : dotR}
											fill="var(--xy-paper)"
											stroke={ser.color}
											strokeWidth={1.1}
											opacity={hi < 0 || hi === i ? 1 : 0.45}
										/>
									))}
								</g>
							);
						})
					: null}

				{hi >= 0 && rows.length > 0 ? (
					<line
						x1={xOf(hi)}
						x2={xOf(hi)}
						y1={pad.t}
						y2={pad.t + innerH}
						stroke="var(--xy-chart)"
						strokeOpacity={0.35}
						strokeDasharray="3 4"
						strokeWidth={1}
					/>
				) : null}

				{!hasData ? (
					<text
						x={w / 2}
						y={pad.t + innerH / 2}
						textAnchor="middle"
						fill="var(--xy-mute)"
						fontSize="12"
					>
						{emptyText}
					</text>
				) : null}
			</svg>

			{tip ? (
				<div
					ref={tipRef}
					className="pointer-events-none absolute z-10 min-w-[11rem] rounded-lg border border-line bg-glass-hover px-2.5 py-2 text-[12px] shadow-[0_2px_12px_rgb(0_0_0_/_0.06)]"
					style={(() => {
						const barX = xOf(hi);
						const gap = 12;
						const placeLeft = barX > pad.l + innerW * 0.5;
						let left = placeLeft ? barX - gap - tipBox.w : barX + gap;
						left = Math.min(
							Math.max(8, left),
							Math.max(8, w - tipBox.w - 8),
						);
						let top = pad.t + 4;
						if (top + tipBox.h > height - 8) {
							top = Math.max(4, height - tipBox.h - 8);
						}
						return {left, top};
					})()}
				>
					<div className="mb-1 flex items-center justify-between gap-4 text-mute">
						<span>{tip.date}</span>
						{tipSummary ? (
							<span className="tabular-nums text-ink">
								{tipSummary(tip.values)}
							</span>
						) : (
							<span className="tabular-nums text-ink">
								{(formatTotal ?? formatY)(tipTotal)}
							</span>
						)}
					</div>
					{series.map(ser => (
						<div
							key={ser.key}
							className="flex items-center justify-between gap-3 py-0.5 text-[11px]"
						>
							<span className="flex items-center gap-1.5 text-ink-soft">
								<span
									className="inline-block h-1.5 w-1.5 rounded-full"
									style={{background: ser.color}}
								/>
								{ser.label}
							</span>
							<span className="tabular-nums text-ink">
								{formatY(tip.values[ser.key] ?? 0)}
							</span>
						</div>
					))}
				</div>
			) : null}
		</div>
	);
}
