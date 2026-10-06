import {useState, type ReactNode} from 'react';
import {cn} from '@/lib/utils';

/**
 * 环形卡：一段弧 + 中心数值 + 底下明细行，点弧或点明细行互相高亮（再点取消）。
 *
 * 从 A3 网页报告的 `donutCard` 搬过来，但配色只吃 `var(--xy-series-*)`：
 * 那份是白底 + 蓝紫板，贴进本 app 就是"别人家的图"。弧长用 stroke-dasharray，
 * 与网页同一几何（0 值段直接不画，避免 0.5 % 下限造出假段）。
 */
export type DonutSegment = {
	key: string;
	label: string;
	value: number | null;
	color: string;
	/** 明细行右侧的百分比覆盖值（命中率这类"段本身就是比率"的卡用）。 */
	percent?: string;
	/** 明细行数值文案覆盖（成本卡要写 ¥，不写 1.2k）。 */
	valueLabel?: string;
};

const SIZE = 132;
const STROKE = 22;

export function DonutCard({
	title,
	sub,
	segments,
	centerValue,
	centerLabel,
	emptyHint,
}: {
	title: string;
	sub: string;
	segments: DonutSegment[];
	centerValue: string;
	centerLabel: string;
	emptyHint?: ReactNode;
}) {
	const [selected, setSelected] = useState<string | null>(null);
	const usable = segments.filter(s => s.value != null && Number.isFinite(s.value) && s.value > 0);
	const total = usable.reduce((acc, s) => acc + (s.value ?? 0), 0);

	if (total <= 0) {
		return (
			<div className="xy-usage-donut min-w-0 bg-paper px-4 py-3" data-donut={title}>
				<DonutHeader title={title} sub={sub} />
				<p className="py-6 text-center text-[12px] text-mute">
					{emptyHint ?? '这一层没有可画的分段（值全为 0 或读不出）。'}
				</p>
			</div>
		);
	}

	const r = (SIZE - STROKE) / 2 - 2;
	const c = 2 * Math.PI * r;
	let offset = 0;

	return (
		<div className="xy-usage-donut min-w-0 bg-paper px-4 py-3" data-donut={title}>
			<DonutHeader title={title} sub={sub} />
			<div className="mt-2 flex items-center gap-3">
				<div className="relative shrink-0" style={{width: SIZE, height: SIZE}}>
					<svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} role="presentation">
						<circle
							cx={SIZE / 2}
							cy={SIZE / 2}
							r={r}
							fill="none"
							stroke="var(--xy-glass)"
							strokeWidth={STROKE}
						/>
						{usable.map(s => {
							const frac = (s.value ?? 0) / total;
							const dash = frac * c;
							const el = (
								<circle
									key={s.key}
									data-donut-seg={s.key}
									cx={SIZE / 2}
									cy={SIZE / 2}
									r={r}
									fill="none"
									stroke={s.color}
									strokeWidth={STROKE}
									strokeDasharray={`${dash} ${c - dash}`}
									strokeDashoffset={-offset + c / 4}
									transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
									opacity={selected && selected !== s.key ? 0.28 : 1}
									onClick={() => setSelected(sel => (sel === s.key ? null : s.key))}
									style={{cursor: 'pointer'}}
								>
									<title>{`${s.label} · ${Math.round(frac * 100)}%`}</title>
								</circle>
							);
							offset += dash;
							return el;
						})}
					</svg>
					<div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
						<span className="text-[15px] tabular-nums text-ink">{centerValue}</span>
						<span className="mt-0.5 text-[10px] text-mute">{centerLabel}</span>
					</div>
				</div>
				<ul className="min-w-0 flex-1">
					{segments.map(s => {
						const frac =
							s.value != null && Number.isFinite(s.value) && total > 0 ? (s.value / total) * 100 : 0;
						return (
							<li
								key={s.key}
								data-donut-row={s.key}
								onClick={() => setSelected(sel => (sel === s.key ? null : s.key))}
								className={cn(
									'flex cursor-pointer items-baseline gap-2 rounded-[6px] px-1.5 py-1 text-[11px]',
									selected === s.key ? 'bg-accent-soft' : 'hover:bg-glass-hover',
								)}
							>
								<span
									aria-hidden
									className="h-2 w-2 shrink-0 rounded-[2px]"
									style={{background: s.color}}
								/>
								<span className="min-w-0 flex-1 truncate text-ink-soft" title={s.label}>
									{s.label}
								</span>
								<span className="shrink-0 tabular-nums text-ink">
									{s.valueLabel ?? (s.value == null ? '数据里没有' : Math.round(s.value).toLocaleString('en-US'))}
								</span>
								<span className="w-10 shrink-0 text-right tabular-nums text-mute">
									{s.percent ?? (s.value == null ? '—' : `${frac.toFixed(1)}%`)}
								</span>
							</li>
						);
					})}
				</ul>
			</div>
		</div>
	);
}

function DonutHeader({title, sub}: {title: string; sub: string}) {
	return (
		<div className="flex items-baseline gap-2">
			<h3 className="text-[13px] font-medium text-ink">{title}</h3>
			<span className="text-[10px] text-mute">{sub}</span>
		</div>
	);
}
