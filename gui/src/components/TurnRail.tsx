import {
	memo,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
		type CSSProperties,

} from 'react';
import {cn} from '@/lib/utils';

export type TurnRailItem = {
	id: string;
	label: string;
	/** Optional progress chip, e.g. "2/2" from that round's todos. */
	badge?: string;
};

type Props = {
	items: TurnRailItem[];
	activeId: string | null;
	onJump: (id: string) => void;
	/**
	 * P-SWITCH②：badge 按需取用。badge 只在面板可见行展示，由父组件
	 * 对挂载行回调计算（内部带缓存）；缺省时回退 item.badge（兼容旧调用）。
	 */
	getBadge?: (id: string) => string | undefined;
	/** messages 换代计数：变化时重算挂载行 badge（配合 getBadge）。 */
	badgeVersion?: number;
};

/** Idle ticks stay glanceable; hover panel lists every round. */
const MAX_TICKS = 15;

/**
 * Panel rows are windowed above this many items: rows share the uniform
 * `.xy-turn-rail-row` height (min-height 26px + single-line ellipsis text),
 * so off-screen rows are replaced by fixed-height spacers. Keeping the
 * threshold low-ish means normal sessions render exactly as before
 * (no spacers, no scroll listener); only huge transcripts switch to the
 * windowed path — which is what kept switch-paint O(rounds) before.
 */
const WINDOW_THRESHOLD = 60;
/** Mirrors `.xy-turn-rail-row { min-height: 26px }`; measured at runtime. */
const ROW_H_DEFAULT = 26;
const OVERSCAN = 6;

type RailLabel = TurnRailItem & {label: string};

type RailTickProps = {
	item: RailLabel;
	active: boolean;
	onJump: (id: string) => void;
};

const RailTick = memo(function RailTick({
	item,
	active,
	onJump,
}: RailTickProps) {
	return (
		<button
			key={item.id}
			type="button"
			data-rail-tick={item.id}
			className={cn('xy-turn-rail-tick', active && 'is-active')}
			aria-label={item.label}
			aria-current={active ? 'true' : undefined}
			onClick={event => {
				event.preventDefault();
				event.stopPropagation();
				onJump(item.id);
			}}
		/>
	);
});

 type RailRowProps = {
	item: RailLabel;
	badge?: string;
	active: boolean;
	rowHover: boolean;
	onJump: (id: string) => void;
	onHover: (id: string | null) => void;
};

const RailRow = memo(function RailRow({
	item,
	badge,
	active,
	rowHover,
	onJump,
	onHover,
}: RailRowProps) {
	return (
		<button
			key={item.id}
			type="button"
			data-rail-id={item.id}
			className={cn(
				'xy-turn-rail-row',
				active && 'is-active',
				!active && rowHover && 'is-hover',
			)}
			onMouseEnter={() => onHover(item.id)}
			onMouseLeave={() => onHover(null)}
			onClick={event => {
				event.preventDefault();
				event.stopPropagation();
				onJump(item.id);
			}}
		>
			<span className="xy-turn-rail-label">
				{badge ? (
					<span className="xy-turn-rail-badge">{badge}</span>
				) : null}
				<span className="xy-turn-rail-text">{item.label}</span>
			</span>
			<span
				className={cn('xy-turn-rail-mark', active && 'is-active')}
				aria-hidden
			/>
		</button>
	);
});
/** Hover panel scrolls once past this many visible rows. */
const SCROLL_AT = 10;
const OPEN_DELAY_MS = 150;
const CLOSE_DELAY_MS = 120;

function oneLine(text: string): string {
	return text.replace(/\s+/g, ' ').trim();
}

/** Gap shrinks as count grows: sparse → dense. */
function gapForCount(n: number): number {
	if (n <= 3) {
		return 14;
	}
	if (n <= 6) {
		return 10;
	}
	if (n <= 10) {
		return 7;
	}
	return 4;
}

/** Downsample the full timeline into ≤15 ticks; keep the active round. */
function sampleTicks(
	items: TurnRailItem[],
	activeId: string | null,
): TurnRailItem[] {
	const n = items.length;
	if (n <= MAX_TICKS) {
		return items;
	}
	const activeIdx = Math.max(
		0,
		items.findIndex(it => it.id === activeId),
	);
	const slotForActive = Math.round(
		(activeIdx / Math.max(1, n - 1)) * (MAX_TICKS - 1),
	);
	const used = new Set<number>();
	const out: TurnRailItem[] = [];
	for (let slot = 0; slot < MAX_TICKS; slot += 1) {
		let idx =
			slot === slotForActive
				? activeIdx
				: Math.round((slot / (MAX_TICKS - 1)) * (n - 1));
		if (used.has(idx)) {
			let found = -1;
			for (let d = 1; d < n; d += 1) {
				const a = idx - d;
				const b = idx + d;
				if (a >= 0 && !used.has(a)) {
					found = a;
					break;
				}
				if (b < n && !used.has(b)) {
					found = b;
					break;
				}
			}
			if (found < 0) {
				continue;
			}
			idx = found;
		}
		used.add(idx);
		out.push(items[idx]!);
	}
	return out;
}

/**
 * Right-middle conversation turn rail.
 * Idle = faint dashes; hover (150ms) = title card; denser as count grows.
 *
 * Perf contract: idle ticks are capped at MAX_TICKS; the hover panel is
 * windowed above WINDOW_THRESHOLD items (uniform row height) so a
 * 5000-round session no longer mounts ~15k DOM nodes per switch.
 */
function turnRailEqual(prev: Props, next: Props): boolean {
	if (prev.activeId !== next.activeId || prev.onJump !== next.onJump) {
		return false;
	}
	if ((prev.badgeVersion ?? 0) !== (next.badgeVersion ?? 0)) {
		return false;
	}
	if (prev.getBadge !== next.getBadge) {
		return false;
	}
	if (prev.items === next.items) {
		return true;
	}
	if (prev.items.length !== next.items.length) {
		return false;
	}
	for (let i = 0; i < prev.items.length; i += 1) {
		const a = prev.items[i]!;
		const b = next.items[i]!;
		if (a.id !== b.id || a.label !== b.label || a.badge !== b.badge) {
			return false;
		}
	}
	return true;
}

export const TurnRail = memo(function TurnRail({items, activeId, onJump, getBadge}: Props) {
	const [hovered, setHovered] = useState(false);
	const [rowHoverId, setRowHoverId] = useState<string | null>(null);
	const enterTimer = useRef(0);
	const leaveTimer = useRef(0);
		const listRef = useRef<HTMLDivElement>(null);
	const labelCacheRef = useRef(new Map<string, RailLabel>());
	const toLabel = useCallback((item: TurnRailItem): RailLabel => {
		const label = oneLine(item.label);
		const cached = labelCacheRef.current.get(item.id);
		if (cached && cached.label === label && cached.badge === item.badge) {
			return cached;
		}
		const next = {...item, label};
		labelCacheRef.current.set(item.id, next);
		return next;
	}, []);

	const windowed = items.length > WINDOW_THRESHOLD;
	// 窗口几何：scrollTop/clientHeight 来自滚动与测量 effect；rowH 运行时
	// 实测（兜底 26px），保证 CSS 行高变化不会让 spacer 失真。
	const [range, setRange] = useState({start: 0, end: 0, rowH: ROW_H_DEFAULT});
	const geoRef = useRef({scrollTop: 0, clientH: 0, rowH: ROW_H_DEFAULT});
	const recomputeRange = useCallback(() => {
		if (!windowed) {
			return;
		}
		const el = listRef.current;
		if (!el) {
			return;
		}
		const geo = geoRef.current;
		geo.scrollTop = el.scrollTop;
		geo.clientH = el.clientHeight;
		const rowH =
			el.querySelector<HTMLElement>('[data-rail-id]')?.offsetHeight ||
			ROW_H_DEFAULT;
		geo.rowH = rowH;
		const first = Math.floor(geo.scrollTop / rowH) - OVERSCAN;
		const count = Math.max(1, Math.ceil(geo.clientH / rowH) + OVERSCAN * 2);
		const start = Math.max(0, first);
		const end = Math.min(items.length, start + count);
		setRange(prev =>
			prev.start === start && prev.end === end && prev.rowH === rowH
				? prev
				: {start, end, rowH},
		);
	}, [items.length, windowed]);

	// 首次挂载 / items 换代（切会话）/ 面板几何变化时重算窗口。
	useEffect(() => {
		recomputeRange();
	}, [recomputeRange, hovered, activeId]);

	const ticks = useMemo(

		() => sampleTicks(items, activeId),
		[items, activeId],
	);
	const tickLabels = useMemo<RailLabel[]>(
		() => ticks.map(toLabel),
		[ticks, toLabel],
	);
	// 面板行：全量（≤阈值，行为与从前一致）或窗口切片；只对挂载的行做
	// label 归一化，切会话不再 O(n) 构建整表 label 对象。
	const rows = useMemo<RailLabel[]>(() => {
		if (!windowed) {
			return items.map(toLabel);
		}
		const slice = items.slice(range.start, range.end);
		return slice.map(toLabel);
	}, [items, range, windowed, toLabel]);

	const capped = items.length > MAX_TICKS;
	const scrollable = items.length >= SCROLL_AT;
	const gapPx = gapForCount(tickLabels.length);
	const dense = tickLabels.length >= 10;

	const clearTimers = useCallback(() => {
		if (enterTimer.current) {
			window.clearTimeout(enterTimer.current);
			enterTimer.current = 0;
		}
		if (leaveTimer.current) {
			window.clearTimeout(leaveTimer.current);
			leaveTimer.current = 0;
		}
	}, []);

	const onEnter = useCallback(() => {
		clearTimers();
		enterTimer.current = window.setTimeout(() => {
			setHovered(true);
			enterTimer.current = 0;
		}, OPEN_DELAY_MS);
	}, [clearTimers]);

	const onLeave = useCallback(() => {
		clearTimers();
		leaveTimer.current = window.setTimeout(() => {
			setHovered(false);
			setRowHoverId(null);
			leaveTimer.current = 0;
		}, CLOSE_DELAY_MS);
	}, [clearTimers]);

	useEffect(() => () => clearTimers(), [clearTimers]);

	// 打开面板时把活动轮滚到可视区（等价于原 scrollIntoView block:'nearest'；
	// 窗口化后活动行可能不在窗口内，用 scrollTop 数学代替 DOM 查询）。
	useEffect(() => {
		if (!activeId || !hovered || !listRef.current) {
			return;
		}
		const index = items.findIndex(it => it.id === activeId);
		if (index < 0) {
			return;
		}
		const el = listRef.current;
		const rowH = geoRef.current.rowH || ROW_H_DEFAULT;
		const top = index * rowH;
		const bottom = top + rowH;
		const view = el.clientHeight;
		if (top < el.scrollTop) {
			el.scrollTop = top;
		} else if (bottom > el.scrollTop + view) {
			el.scrollTop = bottom - view;
		}
	}, [hovered, activeId, items, windowed]);

	const hoverRow = useCallback((id: string | null) => {
		setRowHoverId(id);
	}, []);

	if (items.length < 2) {
		return null;
	}

	const idleStyle = {
		['--xy-rail-gap' as string]: `${gapPx}px`,
	} as CSSProperties;

		return (
		<div
			className={cn(
				'xy-turn-rail',
				hovered && 'is-open',
				dense && 'is-dense',
				capped && 'is-capped',
			)}
			onMouseEnter={onEnter}
			onMouseLeave={onLeave}
			aria-label="对话回合导航"
		>
			<div
				className={cn(
					'xy-turn-rail-idle',
					hovered && 'is-hidden',
					capped && 'is-capped',
				)}
				style={idleStyle}
				aria-hidden={hovered}
			>
					{tickLabels.map(it => (
						<RailTick
							key={it.id}
							item={it}
							active={it.id === activeId}
							onJump={onJump}
						/>
					))}
			</div>

			<div
				className={cn('xy-turn-rail-panel', hovered && 'is-open')}
				aria-hidden={!hovered}
			>
				<div
					ref={listRef}
					className={cn(
						'xy-turn-rail-list',
						scrollable && 'is-scroll',
					)}
					onScroll={windowed ? recomputeRange : undefined}
				>
					{windowed && range.start > 0 ? (
						<div
							style={{height: range.start * range.rowH}}
							aria-hidden
						/>
					) : null}
						{rows.map(it => (
							<RailRow
								key={it.id}
								item={it}
								badge={getBadge ? getBadge(it.id) : it.badge}
								active={it.id === activeId}
								rowHover={it.id === rowHoverId}
								onJump={onJump}
								onHover={hoverRow}
							/>
						))}
					{windowed && range.end < items.length ? (
						<div
							style={{height: (items.length - range.end) * range.rowH}}
							aria-hidden
						/>
					) : null}
				</div>
			</div>
		</div>
	);
}, turnRailEqual);
