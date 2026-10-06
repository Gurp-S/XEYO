/**
 * Token 活动热力图的纯计算：日/周分桶、强度分档、累计序列、中文数量级。
 *
 * 与渲染分开是为了让"分档是不是被最大值绑架""空格与无数据格是否同色"这类判据可测。
 *
 * 指标口径：格子的值是账本自带的 ``tokens``（厂商 ``total_tokens`` 语义，缺省时由
 * prompt+output 落同一字段）。**不是**界面把 命中/未命中/输出 三分类相加——那三桶在
 * 账本里刻意分列（见 ``usage/ledger.py`` 的 v4 口径），相加会造出一个厂商没给过的数。
 */
import type {LiveUsageDay} from '@/lib/api/liveUsage';

export type ActivityView = 'day' | 'week' | 'cumulative';

/** 一格：日视图一天、周视图一周。``value`` 为 null 是"账本没给这个字段"，不是 0。 */
export type ActivityCell = {
	key: string;
	/** 该格起始日（周格 = 周一），ISO ``YYYY-MM-DD``。 */
	start: string;
	/** 上屏用的中文日期。 */
	label: string;
	value: number | null;
	/** 0=零活动，1..4=强度档；无数据与未来日另用 has_data / future 表达。 */
	level: 0 | 1 | 2 | 3 | 4;
	/** 这一天/这一周在账本里有没有行（没有行 = 没跑，不等于"读不出"）。 */
	has_data: boolean;
	/** 周格里有账本行的天数（日格恒 0 或 1）。 */
	days_with_data: number;
	/** 晚于账本/今天的日格：不画值，也不参与任何合计。 */
	future: boolean;
	requests: number | null;
	cost_cny: number | null;
	cost_unknown_requests: number | null;
};

export type ActivityGrid = {
	/** 日视图：列 = 周（周日 → 周六 7 格）。周视图：每列 1 格。 */
	columns: ActivityCell[][];
	/** 月份轴：列索引 → 中文月标签（只在月初那一列出现）。 */
	months: {column: number; label: string}[];
	/** 有非零活动的格数（用于"覆盖 N 天"）。 */
	active_cells: number;
	/** 窗口内 tokens 合计（日视图口径；与累计视图的 total 同式）。 */
	total: number;
	max: number;
	latest_day: string | null;
	earliest_day: string | null;
};

export type CumulativePoint = {day: string; total: number; value: number};

export type CumulativeSeries = {
	points: CumulativePoint[];
	total: number;
	days_with_data: number;
	/** 有行但 tokens 读不出的天数：这些天没进合计，界面要按这个数说明。 */
	days_without_tokens: number;
	from: string | null;
	to: string | null;
};

const DAY_MS = 86_400_000;

/** 热力图窗口：53 周 ≈ 一年，再多就横向溢出到读不动。 */
export const ACTIVITY_WEEKS = 53;

/** 把 ISO 日切成 UTC 毫秒（只用于算星期与周首，不涉及时区换算）。 */
function ms(isoDay: string): number {
	const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDay || '');
	if (!m) return NaN;
	return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function iso(msValue: number): string {
	if (!Number.isFinite(msValue)) return '';
	return new Date(msValue).toISOString().slice(0, 10);
}

/** 周日（网格列内第一行的起点；与 GitHub 同形）。 */
function sundayOf(isoDay: string): string {
	const t = ms(isoDay);
	if (!Number.isFinite(t)) return '';
	return iso(t - new Date(t).getUTCDay() * DAY_MS);
}

function chineseDay(isoDay: string): string {
	const t = ms(isoDay);
	if (!Number.isFinite(t)) return isoDay;
	const d = new Date(t);
	return `${d.getUTCMonth() + 1}月${d.getUTCDate()}日`;
}

function trimZeros(text: string): string {
	return text.replace(/\.0$/, '');
}

/**
 * 中文数量级：1,082,056,006 → 「10.8亿」，12,345 → 「1.2万」，999 → 「999」。
 *
 * 用「万 / 亿」而不是 k/M/B：这一页读的是"跑了多少"，中文语境里 10.8 亿比 1.08B 直读；
 * 阈值 1 万才折算，小数字不硬造单位。读不出回「数据里没有」，不写 0。
 */
export function formatChineseTokens(value: number | null | undefined): string {
	if (value == null || !Number.isFinite(value)) return '数据里没有';
	const n = Math.max(0, Math.round(value));
	if (n >= 1_0000_0000) return `${trimZeros((n / 1_0000_0000).toFixed(1))}亿`;
	if (n >= 1_0000) return `${trimZeros((n / 1_0000).toFixed(1))}万`;
	return n.toLocaleString('en-US');
}

/**
 * 强度分档：对**非零**值取 25/50/75 分位（线性插值），0 恒为 0 档。
 *
 * 不用 max/4 等分：本机账本一天能到 4,933 笔、另一天 8 笔，等分会把 99 % 的格子压成
 * 同一档，图就白画。分位数只看这一份数据的分布（不读时钟、不随机），完全确定。
 */
export function activityLevels(values: (number | null)[]): [number, number, number] | null {
	const nz = values
		.filter((v): v is number => v != null && Number.isFinite(v) && v > 0)
		.sort((a, b) => a - b);
	if (nz.length === 0) return null;
	const at = (q: number) => {
		const pos = (nz.length - 1) * q;
		const lo = Math.floor(pos);
		const hi = Math.ceil(pos);
		return nz[lo]! + (nz[hi]! - nz[lo]!) * (pos - lo);
	};
	const p25 = at(0.25);
	const p50 = at(0.5);
	const p75 = at(0.75);
	// 分布塌成一点（只有一个非零日）时三档相等：把上界压到该值之下，那一格才落在 4 档，
	// 而不是因为"值 == 上界"掉进 3 档。
	if (!(p75 > p25)) return [p25 / 4, p25 / 2, (p25 * 3) / 4];
	return [p25, p50, p75];
}

function levelOf(value: number | null, cuts: [number, number, number] | null): 0 | 1 | 2 | 3 | 4 {
	if (value == null) return 0;
	if (!Number.isFinite(value) || value <= 0) return 0;
	if (!cuts) return 4;
	if (value <= cuts[0]) return 1;
	if (value <= cuts[1]) return 2;
	if (value <= cuts[2]) return 3;
	return 4;
}

function sumOf(days: LiveUsageDay[], pick: (d: LiveUsageDay) => number | null | undefined): number | null {
	let total: number | null = null;
	for (const d of days) {
		const v = pick(d);
		if (v == null || !Number.isFinite(v)) continue;
		total = (total ?? 0) + v;
	}
	return total;
}

function cellFrom(
	key: string,
	start: string,
	label: string,
	days: LiveUsageDay[],
	cuts: [number, number, number] | null,
	opts?: {future?: boolean},
): ActivityCell {
	const future = opts?.future === true;
	// 「这一天没跑」与「跑了但 tokens 读不出」必须分家：前者 value=0（灰格），
	// 后者 value=null（格子描一圈虚线边）。都取 sumOf 的话空数组会回 null，两者就混了。
	const value = days.length === 0 ? 0 : sumOf(days, d => d.tokens);
	return {
		key,
		start,
		label,
		value: future ? null : value,
		level: future ? 0 : levelOf(value, cuts),
		has_data: !future && days.length > 0,
		days_with_data: days.filter(d => (d.requests ?? 0) > 0).length,
		future,
		requests: future ? null : sumOf(days, d => d.requests),
		cost_cny: future ? null : sumOf(days, d => d.cost_cny),
		cost_unknown_requests: future ? null : sumOf(days, d => d.cost_unknown_requests),
	};
}

function monthLabelOf(day: string): string {
	const t = ms(day);
	if (!Number.isFinite(t)) return '';
	const d = new Date(t);
	// 只在月初 7 天内的那一列标月份，否则月份标签会漂到月中。
	if (d.getUTCDate() > 7) return '';
	return `${d.getUTCMonth() + 1}月`;
}

/**
 * 日 / 周网格。``today`` 由调用方给（本模块不读时钟 ⇒ 可测）。
 *
 * 三种格子说三种话：有活动（按档着色）、账本里没有这一天（空格）、晚于今天
 * （不画）。把"没跑"与"读不出"混成同一格，就是把零活动画成缺数据。
 */
export function buildActivityGrid(
	days: LiveUsageDay[],
	view: ActivityView,
	today: string,
): ActivityGrid {
	const byDay = new Map<string, LiveUsageDay[]>();
	for (const d of days) {
		if (!Number.isFinite(ms(d.day))) continue;
		const list = byDay.get(d.day) ?? [];
		list.push(d);
		byDay.set(d.day, list);
	}
	const present = [...byDay.keys()].sort();
	const latest = present.length ? present[present.length - 1]! : null;
	const earliest = present.length ? present[0]! : null;
	const anchor = Number.isFinite(ms(today)) ? today : latest;
	// 账本为空 ⇒ 整张图不画：画 371 个灰格会把"这台机器还没记过账"读成"一年都没跑"。
	if (!anchor || days.length === 0) {
		return {columns: [], months: [], active_cells: 0, total: 0, max: 0, latest_day: null, earliest_day: null};
	}

	const lastWeekStart = sundayOf(anchor);
	const firstWeekStart = iso(ms(lastWeekStart) - (ACTIVITY_WEEKS - 1) * 7 * DAY_MS);
	const weekStarts: string[] = [];
	for (let t = ms(firstWeekStart); t <= ms(lastWeekStart); t += 7 * DAY_MS) weekStarts.push(iso(t));

	const dayValue = (day: string): number | null => sumOf(byDay.get(day) ?? [], d => d.tokens);
	const weekValue = (week: string): number | null =>
		sumOf(
			[0, 1, 2, 3, 4, 5, 6].flatMap(i => byDay.get(iso(ms(week) + i * DAY_MS)) ?? []),
			d => d.tokens,
		);

	const dayValues = weekStarts.flatMap(w =>
		[0, 1, 2, 3, 4, 5, 6].map(i => dayValue(iso(ms(w) + i * DAY_MS))),
	);
	const weekValues = weekStarts.map(weekValue);
	const cuts = activityLevels(view === 'week' ? weekValues : dayValues);

	const columns: ActivityCell[][] = [];
	const months: {column: number; label: string}[] = [];
	let lastMonth = '';
	weekStarts.forEach((week, index) => {
		const label = monthLabelOf(week);
		if (label && label !== lastMonth) {
			months.push({column: index, label});
			lastMonth = label;
		}
		if (view === 'week') {
			const rows = [0, 1, 2, 3, 4, 5, 6].flatMap(i => byDay.get(iso(ms(week) + i * DAY_MS)) ?? []);
			columns.push([
				cellFrom(week, week, `${chineseDay(week)} ~ ${chineseDay(iso(ms(week) + 6 * DAY_MS))}`, rows, cuts),
			]);
			return;
		}
		columns.push(
			[0, 1, 2, 3, 4, 5, 6].map(i => {
				const day = iso(ms(week) + i * DAY_MS);
				const future = ms(day) > ms(anchor);
				return cellFrom(day, day, chineseDay(day), byDay.get(day) ?? [], cuts, {future});
			}),
		);
	});

	const all = columns.flat();
	const totals = view === 'week' ? weekValues : dayValues;
	const finite = totals.filter((v): v is number => v != null && Number.isFinite(v));
	return {
		columns,
		months,
		active_cells: all.filter(c => (c.value ?? 0) > 0).length,
		total: finite.reduce((a, b) => a + b, 0),
		max: finite.length ? Math.max(...finite) : 0,
		latest_day: latest,
		earliest_day: earliest,
	};
}

/** 累计总量：按有 tokens 的日子往前累加（读不出的日子不进合计，只报条数）。 */
export function buildCumulative(days: LiveUsageDay[]): CumulativeSeries {
	const rows = [...days]
		.filter(d => Number.isFinite(ms(d.day)))
		.sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));
	const points: CumulativePoint[] = [];
	let running = 0;
	let missing = 0;
	for (const d of rows) {
		const v = d.tokens;
		if (v == null || !Number.isFinite(v)) {
			missing += 1;
			continue;
		}
		running += v;
		points.push({day: d.day, total: running, value: v});
	}
	return {
		points,
		total: running,
		days_with_data: points.length,
		days_without_tokens: missing,
		from: points.length ? points[0]!.day : null,
		to: points.length ? points[points.length - 1]!.day : null,
	};
}
