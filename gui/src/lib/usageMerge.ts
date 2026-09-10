/**
 * usageMerge.ts — 用量报表合并（「全部」跨厂商视图）纯逻辑。
 *
 * 从 UsagePanel 抽出的原因：合并口径是 v4 契约的一部分（三分类 + hit_rate +
 * 成功结算 requests，无金额/无吞吐大数；模型行按「输入未命中」降序），抽成纯
 * 模块后才能用单测钉死，避免与渲染耦合。与 python/usage/{ledger,vendor,combine}.py
 * 的 _bucket_view / withDerived 口径保持一致。
 */

import type {
	UsageBucket,
	UsageDayPoint,
	UsageModelBlock,
	UsageReport,
} from '@/lib/api';

/** 空桶 / 兜底：与后端 totals schema 对齐。 */
export function emptyBucket(): UsageBucket {
	return {
		requests: 0,
		input_hit: 0,
		input_miss: 0,
		output: 0,
		input_total: 0,
		hit_rate: null,
	};
}

/** 由 hit/miss 合成 input_total + hit_rate（与后端口径一致）。 */
export function withDerived(b: {
	requests: number;
	input_hit: number;
	input_miss: number;
	output: number;
}): UsageBucket {
	const inputTotal = b.input_hit + b.input_miss;
	return {
		...b,
		input_total: inputTotal,
		hit_rate:
			inputTotal > 0
				? Math.round((b.input_hit / inputTotal) * 1000) / 10
				: null,
	};
}

/** 对带 day 的日点派生 input_total + hit_rate（保留维度键）。 */
function deriveDayPoint(
	p: {
		day: string;
	} & Pick<UsageBucket, 'requests' | 'input_hit' | 'input_miss' | 'output'>,
): UsageDayPoint {
	return {day: p.day, ...withDerived(p)};
}

/** 按天累加合并两组日序列（保持原顺序）。 */
function mergeSeries(
	a: UsageDayPoint[],
	b: UsageDayPoint[],
): UsageDayPoint[] {
	const map = new Map<string, UsageDayPoint>();
	for (const p of [...a, ...b]) {
		const cur =
			map.get(p.day) ?? ({day: p.day, ...emptyBucket()} as UsageDayPoint);
		cur.requests += p.requests;
		cur.input_hit += p.input_hit;
		cur.input_miss += p.input_miss;
		cur.output += p.output;
		map.set(p.day, cur);
	}
	return [...map.values()];
}

/**
 * 合并多个厂商的用量（「全部」视图）：模型分块去重合并、系列按天累加、总额相加。
 *
 * v4：输出层只有三分类 + hit_rate + requests（无金额字段传入/传出）；
 * 模型行排序 = 输入未命中(新增内容)降序 → requests 降序 → 厂商/模型字典序。
 */
export function mergeReports(reports: UsageReport[]): UsageReport {
	const sumHitMissOut = (k: 'input_hit' | 'input_miss' | 'output') =>
		reports.reduce((a, r) => a + (r.totals?.[k] ?? 0), 0);
	const requests = reports.reduce(
		(a, r) => a + (r.totals?.requests ?? 0),
		0,
	);
	const totals = withDerived({
		requests,
		input_hit: sumHitMissOut('input_hit'),
		input_miss: sumHitMissOut('input_miss'),
		output: sumHitMissOut('output'),
	});
	// 多来源报告的 source 如实反映"混合"（后端单报告只回 vendor/local）。
	const sources = new Set(reports.map(r => r.source).filter(Boolean));
	const hasV = sources.has('vendor');
	const hasL = sources.has('local');
	const hasM = sources.has('mixed');
	const source =
		(hasV && (hasL || hasM)) || (hasL && hasM)
			? 'mixed'
			: hasV
				? 'vendor'
				: hasL
					? 'local'
					: hasM
						? 'mixed'
						: 'local';
	const seriesMap = new Map<string, UsageDayPoint>();
	for (const r of reports) {
		for (const p of r.series ?? []) {
			const cur =
				seriesMap.get(p.day) ??
				({day: p.day, ...emptyBucket()} as UsageDayPoint);
			cur.requests += p.requests;
			cur.input_hit += p.input_hit;
			cur.input_miss += p.input_miss;
			cur.output += p.output;
			seriesMap.set(p.day, cur);
		}
	}
	const series = [...seriesMap.values()].map(p => deriveDayPoint(p));
	// 跨厂商去重 same provider+model 分块，避免重复计数；排序按「输入未命中」降序（B1）。
	const modelMap = new Map<string, UsageModelBlock>();
	for (const m of reports.flatMap(r => r.models ?? [])) {
		const key = `${m.provider}:${m.model}`;
		const cur =
			modelMap.get(key) ??
			({
				provider: m.provider,
				model: m.model,
				...emptyBucket(),
				series: [] as UsageDayPoint[],
			} as UsageModelBlock);
		cur.requests += m.requests;
		cur.input_hit += m.input_hit;
		cur.input_miss += m.input_miss;
		cur.output += m.output;
		cur.series = mergeSeries(cur.series, m.series ?? []);
		modelMap.set(key, cur);
	}
	const models = [...modelMap.values()]
		.map(m => ({...m, series: m.series.map(p => deriveDayPoint(p))}))
		.map(m => ({...m, ...withDerived(m)}))
		.sort(
			(a, b) =>
				b.input_miss - a.input_miss ||
				b.requests - a.requests ||
				a.provider.localeCompare(b.provider) ||
				a.model.localeCompare(b.model),
		);
	return {
		days: reports[0]?.days ?? [],
		totals,
		source,
		vendor_ok: reports.some(r => r.vendor_ok),
		series,
		models,
		keys: reports.flatMap(r => r.keys ?? []),
	};
}
