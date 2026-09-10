/**
 * usageMerge.test.ts — 用量报表合并口径契约（B1 v4）。
 *
 * 对齐 DeepSeek Harness usage-stats：每层 {requests, input_hit, input_miss,
 * output, input_total, hit_rate}，无金额 / 无吞吐大数；模型行按「输入未命中」
 * 降序；跨厂商同 provider+model 去重求和。与后端 ledger/vendor 的 _bucket_view
 * 同口径。
 */

import {describe, expect, it} from 'vitest';
import type {UsageBucket, UsageDayPoint, UsageModelBlock, UsageReport} from '@/lib/api';
import {mergeReports} from '@/lib/usageMerge';

function bucket(
	requests: number,
	input_hit: number,
	input_miss: number,
	output: number,
): UsageBucket {
	const inputTotal = input_hit + input_miss;
	return {
		requests,
		input_hit,
		input_miss,
		output,
		input_total: inputTotal,
		hit_rate: inputTotal > 0 ? Math.round((input_hit / inputTotal) * 1000) / 10 : null,
	};
}

function dayPoint(day: string, input_hit: number, input_miss: number, output: number): UsageDayPoint {
	return {day, ...bucket(1, input_hit, input_miss, output)};
}

function modelBlock(
	provider: string,
	model: string,
	input_miss: number,
	output: number,
	series: UsageDayPoint[] = [],
): UsageModelBlock {
	const input_hit = input_miss === 0 ? 100 : 0; // 有未命中即无命中，便于断言排序
	return {
		provider,
		model,
		...bucket(input_hit === 0 ? 1 : 2, input_hit, input_miss, output),
		series,
	};
}

function report(
	source: 'vendor' | 'local',
	over: Partial<UsageReport> = {},
): UsageReport {
	return {
		days: ['2026-09-08', '2026-09-09'],
		totals: bucket(0, 0, 0, 0),
		source,
		vendor_ok: source === 'vendor',
		series: [],
		models: [],
		keys: [],
		...over,
	};
}

describe('mergeReports（v4 合并契约）', () => {
	it('totals 相加并派生 input_total/hit_rate；无金额/吞吐大数字段（红线）', () => {
		const a = report('vendor', {
			totals: bucket(3, 600, 200, 100),
		});
		const b = report('local', {
			totals: bucket(2, 0, 300, 50),
		});
		const out = mergeReports([a, b]);
		expect(out.totals).toEqual(bucket(5, 600, 500, 150));
		// v4 红线：报表任何层都不带金额 / 吞吐大数字段
		expect(out.totals).not.toHaveProperty('cost');
		expect(out.totals).not.toHaveProperty('tokens');
		expect(out).not.toHaveProperty('cost_source');
		expect(out).not.toHaveProperty('lifetime_cost');
		expect(out.models).toEqual([]);
	});

	it('series 按天累加并派生每点三分类', () => {
		const a = report('vendor', {
			series: [dayPoint('2026-09-08', 40, 10, 5), dayPoint('2026-09-09', 100, 0, 20)],
		});
		const b = report('local', {
			series: [dayPoint('2026-09-08', 0, 30, 5)],
		});
		const out = mergeReports([a, b]);
		expect(out.series).toHaveLength(2);
		const d8 = out.series.find(p => p.day === '2026-09-08')!;
		expect(d8).toEqual({day: '2026-09-08', ...bucket(2, 40, 40, 10)});
		const d9 = out.series.find(p => p.day === '2026-09-09')!;
		expect(d9.input_total).toBe(100);
		expect(d9.hit_rate).toBe(100);
	});

	it('同 provider+model 跨报告去重求和；模型按输入未命中降序', () => {
		const a = report('vendor', {
			models: [modelBlock('deepseek', 'deepseek-v4-flash', 300, 30)],
		});
		const b = report('local', {
			models: [
				modelBlock('deepseek', 'deepseek-v4-flash', 500, 50), // 同款 → 合并
				modelBlock('zhipu', 'glm-4.5-air', 900, 90), // 未命中最大 → 排第一
			],
		});
		const out = mergeReports([a, b]);
		expect(out.models).toHaveLength(2);
		expect(out.models[0].model).toBe('glm-4.5-air'); // 输入未命中 900 > 800
		expect(out.models[0].input_miss).toBe(900);
		const flash = out.models.find(m => m.model === 'deepseek-v4-flash')!;
		expect(flash.input_miss).toBe(800); // 300 + 500 去重求和
		expect(flash.requests).toBe(2);
		expect(flash.input_total).toBe(800);
	});

	it('跨厂商同款模型系列也按天合并', () => {
		const series = [dayPoint('2026-09-09', 0, 100, 10)];
		const a = report('vendor', {
			models: [modelBlock('deepseek', 'deepseek-v4-flash', 100, 10, series)],
		});
		const b = report('local', {
			models: [modelBlock('deepseek', 'deepseek-v4-flash', 100, 10, series)],
		});
		const out = mergeReports([a, b]);
		const flash = out.models.find(m => m.model === 'deepseek-v4-flash')!;
		expect(flash.series).toHaveLength(1);
		expect(flash.series[0].input_miss).toBe(200);
		expect(flash.series[0].requests).toBe(2);
	});

	it('source 如实反映混合来源；纯厂商保持 vendor', () => {
		expect(mergeReports([report('vendor'), report('local')]).source).toBe('mixed');
		expect(mergeReports([report('vendor'), report('vendor')]).source).toBe('vendor');
		expect(mergeReports([report('local')]).source).toBe('local');
	});
});
