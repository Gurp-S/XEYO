/**
 * 用量页的读数措辞（从 `components/A3NativePanel.tsx` 抽出，供下钻/环形卡共用）。
 *
 * 三条硬规矩，抽出来也不改：
 * - 缺字段说「数据里没有」，不补 0、不画横杠；
 * - 账上明写「无价目」（`cost_cny: null`，上游核实过没有权威价目）说「无价目」，
 *   写成 ¥0.00 等于把"费用未知"读成"免费"；
 * - 合计里混了无价目行 ⇒ 金额后补「部分未知」，这个数不是完整合计。
 */
import {formatCacheHitPercent, formatMoney, formatTokenCount} from '@/lib/formatUsage';

/** 数据里没有这项时统一说的话——不猜、不用 0 顶、不静默画 dashes。 */
export const NO_DATA = '数据里没有';
/** 账上明确写了「无价目」（`cost_cny: null`）时说的话。 */
export const NO_PRICE = '无价目';
/** 合计里混了无价目行时补的限定词：这个数不是完整合计。 */
export const PARTIAL = '部分未知';

type Num = number | null | undefined;

export function intLabel(value: Num): string {
	return value == null ? NO_DATA : Math.round(value).toLocaleString('en-US');
}

export function tokenLabel(value: Num): string {
	return value == null ? NO_DATA : formatTokenCount(value);
}

/** 紧凑 token，去掉 " tok" 单位——用在成对的「命中/输入」这种单位已在表头言明的格子里。 */
export function compactToken(value: Num): string {
	return value == null ? NO_DATA : formatTokenCount(value).replace(/ tok$/, '');
}

/**
 * 成本：统一走 `formatMoney`（≥¥1 两位、<¥1 四位）；0 是真值，不当缺失。
 *
 * - `null`（后端说过：无权威价目）→「无价目」，不写 0、不写空串；
 * - `undefined`（这一层没读到该字段）→「数据里没有」，不冒充无价目；
 * - `unknown > 0`（合计里有无价目行）→ 金额后补「部分未知」。
 */
export function costLabel(value?: Num, unknown?: Num): string {
	if (value === null) return NO_PRICE;
	if (value === undefined) return NO_DATA;
	if (!Number.isFinite(value)) return NO_PRICE;
	const money = formatMoney(value);
	return unknown != null && unknown > 0 ? `${money}（${PARTIAL}）` : money;
}

/** 命中率优先用 hit/miss 两个分母算（与网页同式），两者都没有才退到 hit_rate 字段。 */
export function rateLabel(day: {
	cache_hit?: Num;
	cache_miss?: Num;
	hit_rate?: Num;
}): string {
	const oneDecimal =
		day.cache_hit != null && day.cache_miss != null
			? formatCacheHitPercent(day.cache_hit, day.cache_miss)
			: null;
	if (oneDecimal) return `${oneDecimal}%`;
	if (day.hit_rate != null) return `${(day.hit_rate * 100).toFixed(1)}%`;
	return NO_DATA;
}

export function timeLabel(ts?: Num): string {
	if (ts == null) return NO_DATA;
	const date = new Date(ts * 1000);
	return Number.isNaN(date.getTime()) ? NO_DATA : date.toTimeString().slice(0, 8);
}

export function shortModel(model?: string): string {
	return (model || '').split('/').pop() || '未记模型';
}

/**
 * 聚合时刻：后端给的是带偏移的 ISO（`2026-10-03T03:00:50+08:00`），
 * 直接上屏是一串读不动的字符；解析不了就原样给回去，不编一个时间。
 */
export function generatedLabel(iso: string): string {
	if (!iso) return NO_DATA;
	const date = new Date(iso);
	return Number.isNaN(date.getTime())
		? iso
		: date.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
}

/** 验收判据三态：true 已验收 / false 快照过但未验收 / null·undefined 从没进过快照。 */
export function snapshotLabel(accepted: boolean | null | undefined): string {
	if (accepted === true) return '已验收';
	if (accepted === false) return '待验收';
	return '未快照';
}
