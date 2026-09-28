/**
 * A3NativePanel.test.tsx — 原生视图的四条硬账。
 *
 * 1. KPI 逐个来自 payload，缺字段就说"数据里没有"，不补 0、不画假柱；
 * 2. `accepted` 是服务端的验收判据，界面**只展示**：fixture 特意让"数据很好但未验收"
 *    与"数据残缺但已验收"同时存在——只要界面从数字反推判据，这两条就会互相打脸；
 * 3. 报告不在 / 数据读不出时，界面说的话要和证据一致（容器那层负责，见文件末尾两条）；
 * 4. 颜色全部走主题令牌，源码里不许出现写死色（这条把"不再是贴进来的网页"钉成机器判据）。
 *
 * fixture 全部是确定值：不读时钟、不读 locale（生成时间只做存在性断言，不比字符串）。
 */
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';

const dataMock = vi.fn();
const dayMock = vi.fn();
const reportMock = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		getMemoryReportData: () => dataMock(),
		getMemoryReportDay: (day: string) => dayMock(day),
		getMemoryReport: () => reportMock(),
		runMemorySnapshot: vi.fn(),
		memoryReportViewUrl: () => 'http://127.0.0.1:8000/v1/settings/memory/report/view',
	};
});

vi.mock('@/lib/toast', () => ({
	toast: {error: vi.fn(), success: vi.fn()},
}));

// jsdom 没有 ResizeObserver，而 UsageChart 用它量容器宽度。
class ResizeObserverStub {
	observe(): void {}
	unobserve(): void {}
	disconnect(): void {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub);

/* eslint-disable import/first */
import {A3NativePanel} from './A3NativePanel';
import {A3SnapshotPanel} from './A3SnapshotPanel';
import type {A3ReportData} from '@/lib/api';
import {formatMoney} from '@/lib/formatUsage';

/** 24 桶：只在 09 点挂 n 笔，其余为 0。 */
const hours = (n: number, at = 9) =>
	Array.from({length: 24}, (_, i) => (i === at ? n : 0));

const DAY_OK: A3ReportData['days'][number] = {
	day: '2026-09-27',
	// 数据很漂亮，但报告判它未验收：界面必须跟着判据说"待验收"。
	accepted: false,
	requests: 42,
	prompt_tokens: 1_200_000,
	cache_hit: 950_000,
	cache_miss: 50_000,
	hit_rate: 0.95,
	c2_count: 3,
	output: 9_000,
	cost_cny: 1.5,
	sessions: 5,
	turns: 12,
	hour_counts: hours(12),
	hour_unknown: 0,
	by_model: [
		{
			provider: 'deepseek',
			model: 'XenYon/deepseek-v4-flash',
			requests: 42,
			prompt_tokens: 1_200_000,
			cache_hit: 950_000,
			cache_miss: 50_000,
			hit_rate: 0.95,
			output: 9_000,
			cost_cny: 1.5,
		},
	],
};

const DAY_HOLES: A3ReportData['days'][number] = {
	day: '2026-09-28',
	// 数据残缺却被验收：界面不能因为"请求读不出来"就把判据翻成待验收。
	accepted: true,
	requests: null,
	prompt_tokens: 2_000_000,
	cache_hit: null,
	cache_miss: null,
	hit_rate: 0.5,
	c2_count: 0,
	output: 4_000,
	cost_cny: null,
	sessions: 7,
	turns: 20,
	hour_counts: hours(20, 3),
	hour_unknown: 2,
	by_model: [],
};

const DATA: A3ReportData = {
	ok: true,
	generated_at: '2026-09-27T18:31:19.658759+00:00',
	source: {path: 'D:/lea/XenYon code/docs/A3-monitor.html', bytes: 10_629_939, mtime: 1},
	day_count: 2,
	days: [DAY_OK, DAY_HOLES],
};

const kpiText = (container: HTMLElement, label: string) =>
	container.querySelector(`[data-a3-kpi="${label}"]`)?.textContent ?? '';

beforeEach(() => {
	dataMock.mockReset();
	dayMock.mockReset();
	reportMock.mockReset();
});

afterEach(() => {
	cleanup();
});

describe('KPI 来自数据', () => {
	it('八个 KPI 逐项对得上 fixture（默认选中最后一天）', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		expect(kpiText(container, '命中率')).toContain('50.0%');
		expect(kpiText(container, '输出 token')).toContain('4.00k tok');
		expect(kpiText(container, '输入 token')).toContain('2.00M tok');
		expect(kpiText(container, 'C2')).toContain('0');
		expect(kpiText(container, '会话数')).toContain('7');
		// 0 是真值：不许把它当成缺失渲染成"数据里没有"。
		expect(kpiText(container, 'C2')).not.toContain('数据里没有');
	});

	it('缺字段的 KPI 直说"数据里没有"，单位成本不编数', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		expect(kpiText(container, '请求')).toContain('数据里没有');
		expect(kpiText(container, '成本')).toContain('数据里没有');
		expect(kpiText(container, '单位成本')).toContain('数据里没有');
	});

	it('切到数据完整的一天：KPI 与分模型表跟着换', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的快照日期'}), {
			target: {value: DAY_OK.day},
		});

		expect(kpiText(container, '命中率')).toContain('95.0%');
		expect(kpiText(container, '请求')).toContain('42');
		expect(kpiText(container, '成本')).toContain('¥1.50');
		expect(kpiText(container, '输出 token')).toContain('9.00k tok');
		// 单位成本 = 1.5 / 42 ≈ 0.0357：界面算的是"这一天的比值"，不是新口径；
		// 金额 <¥1 走 4 位小数（旧口径的 6 位 ¥0.035714 已废）。
		expect(kpiText(container, '单位成本')).toContain('¥0.0357');
		// 模型列走 shortModel（取最后一段）：厂商/协议名保留拉丁原文，不截成乱码。
		expect(screen.getByText('deepseek-v4-flash')).toBeInTheDocument();
	});

	it('无时间戳的轮数要说出来，不静默丢', () => {
		render(<A3NativePanel data={DATA} />);

		expect(screen.getByText(/2 轮无时间戳，未计入/)).toBeInTheDocument();
	});

	it('输入 token 的缓存构成条复用 usageSegments：有数据才画', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		// 默认选中的那天 hit/miss 都是 null ⇒ 不画（宽度钳制会把它画成假的五五分）。
		expect(container.querySelector('[data-a3-hitmiss]')).toBeNull();

		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的快照日期'}), {
			target: {value: DAY_OK.day},
		});

		const bar = container.querySelector('[data-a3-hitmiss]');
		expect(bar).not.toBeNull();
		// 分段文案与单位来自被复用的模块（tokens 口径，不是请求数）。
		expect(bar?.getAttribute('aria-label')).toBe('输入 · 命中缓存 950.00k tok · 输入 · 未命中 50.00k tok');
		expect(screen.getByText('输入 · 命中缓存 950.00k tok')).toBeInTheDocument();
		// 两段宽度之和 = 100%（分母就是这两半之和，即当日输入）。
		const widths = [...(bar?.querySelectorAll('span') ?? [])].map(s =>
			(s as HTMLElement).style.width,
		);
		expect(widths.reduce((acc, w) => acc + Number.parseFloat(w || '0'), 0)).toBeCloseTo(100, 1);
	});
});

describe('小时分布：24 槽都在标度上', () => {
	it('渲染 24 个按小时定位的槽位，零轮次的小时也在（默认日只有 03 点有轮次）', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		const slots = [...container.querySelectorAll('[data-a3-hour]')];
		// 24 格、顺序即小时 0..23——杜绝"有几桶画几格"把柱子挤到左边。
		expect(slots).toHaveLength(24);
		expect(slots.map(s => s.getAttribute('data-a3-hour'))).toEqual(
			Array.from({length: 24}, (_, i) => String(i)),
		);
		// 零轮次小时占位（0 点 = 0），有轮次小时如实（默认日 03 点 = 20）。
		expect(slots[0]?.getAttribute('data-a3-hour-count')).toBe('0');
		expect(slots[3]?.getAttribute('data-a3-hour-count')).toBe('20');
	});

	it('x 轴刻度落在 0/6/12/18/23，小时可读', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		const axis = container.querySelector('[data-a3-hour-axis]');
		expect(axis).not.toBeNull();
		expect(
			[...(axis?.querySelectorAll('.tabular-nums') ?? [])].map(e => e.textContent),
		).toEqual(['0', '6', '12', '18', '23']);
	});
});

describe('读数精度', () => {
	it('formatMoney：≥¥1 两位、0<¥1 四位、恰好 0 用两位', () => {
		expect(formatMoney(18.764621)).toBe('¥18.76');
		expect(formatMoney(5.844108)).toBe('¥5.84');
		expect(formatMoney(0.013312)).toBe('¥0.0133');
		expect(formatMoney(0)).toBe('¥0.00');
	});

	it('KPI 渲染按量级给精度：总额两位、单位成本四位', () => {
		const {container} = render(<A3NativePanel data={DATA} />);
		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的快照日期'}), {
			target: {value: DAY_OK.day},
		});

		// 成本 1.5 ≥ ¥1 → ¥1.50；旧的 6 位小数口径不再出现。
		expect(kpiText(container, '成本')).toContain('¥1.50');
		expect(kpiText(container, '成本')).not.toContain('1.500000');
		// 单位成本 1.5/42 ≈ 0.0357 < ¥1 → 四位小数。
		expect(kpiText(container, '单位成本')).toContain('¥0.0357');
	});

	it('分模型「命中/输入」用紧凑单位（19.21M / 20.88M 式），不再是原始整数', () => {
		render(<A3NativePanel data={DATA} />);
		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的快照日期'}), {
			target: {value: DAY_OK.day},
		});

		// DAY_OK：命中 950000 / 输入 950000+50000=1000000。
		expect(screen.getByText('950.00k / 1.00M')).toBeInTheDocument();
		expect(screen.queryByText(/950,000/)).toBeNull();
	});
});

describe('验收判据只透传（补：数字漂亮也不改判据）', () => {
	it('accepted:false 且请求/成本/命中率都齐全的一天，仍判"待验收"', () => {
		// DAY_OK：请求 42、成本 ¥1.50、命中率 95%——数据很完整，但服务端 accepted:false。
		const {container} = render(<A3NativePanel data={{...DATA, days: [DAY_OK]}} />);

		// 数字确实是"漂亮"的（若从数字反推判据，这里就会被误判成已验收）。
		expect(kpiText(container, '请求')).toContain('42');
		expect(kpiText(container, '成本')).toContain('¥1.50');
		expect(kpiText(container, '命中率')).toContain('95.0%');
		// 但判据只认服务端的 accepted：顶栏与状态列都必须是"待验收"。
		expect(screen.getByText(/快照状态：待验收/)).toBeInTheDocument();
		expect(screen.queryByText('已验收')).toBeNull();
	});
});

describe('验收判据只透传', () => {
	it('两行的状态各自等于服务端的 accepted，不由数字反推', () => {
		render(<A3NativePanel data={DATA} />);

		// 数据漂亮但未验收 ⇒ 待验收；数据残缺但已验收 ⇒ 已验收。
		expect(screen.getAllByText('待验收')).toHaveLength(1);
		expect(screen.getAllByText('已验收')).toHaveLength(1);
		// 判据要钉在**它自己那一天**上：串了行就等于界面自己算了一个判据。
		expect(screen.getByText('待验收').closest('tr')?.textContent).toContain(DAY_OK.day);
		expect(screen.getByText('已验收').closest('tr')?.textContent).toContain(DAY_HOLES.day);
	});

	it('顶栏状态跟着选中那天走', () => {
		render(<A3NativePanel data={DATA} />);

		expect(screen.getByText(/快照状态：已验收/)).toBeInTheDocument();

		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的快照日期'}), {
			target: {value: DAY_OK.day},
		});

		expect(screen.getByText(/快照状态：待验收/)).toBeInTheDocument();
	});

	it('accepted 为 false 的一天不出现任何"已验收"字样', () => {
		render(<A3NativePanel data={{...DATA, days: [DAY_OK]}} />);

		expect(screen.queryByText('已验收')).toBeNull();
		expect(screen.getByText(/快照状态：待验收/)).toBeInTheDocument();
	});
});

describe('诚实的空态', () => {
	it('报告里没有任何一天：明说，不画空图、不摆 0 值 KPI', () => {
		const {container} = render(
			<A3NativePanel data={{...DATA, day_count: 0, days: []}} />,
		);

		expect(screen.getByText('报告里没有任何一天的数据。')).toBeInTheDocument();
		expect(container.querySelector('[data-a3-kpi="命中率"]')).toBeNull();
		expect(screen.queryByText('请求 · 小时分布')).toBeNull();
	});

	it('分模型行为空时说"没有分模型行"，不渲染空表头当作有数据', () => {
		render(<A3NativePanel data={DATA} />);

		expect(screen.getByText('这一天的报告数据里没有分模型行。')).toBeInTheDocument();
	});
});

describe('不出现写死颜色', () => {
	const src = readFileSync(resolve(process.cwd(), 'src/components/A3NativePanel.tsx'), 'utf8');
	// 剥注释：文档里提到的「原先是白底」不算违规（与 themePairing.guard 同一手法）。
	const code = src
		.replace(/\/\*[\s\S]*?\*\//g, '')
		.split('\n')
		.filter(l => !/^\s*(\/\/|\*)/.test(l))
		.join('\n');

	it('扫描面本身有效（防止文件读空导致断言空跑）', () => {
		expect(code.length).toBeGreaterThan(1000);
		expect(code).toContain('var(--xy-chart)');
	});

	it('没有 bg-white / text-white', () => {
		expect(code).not.toMatch(/\bbg-white\b/);
		expect(code).not.toMatch(/\btext-white\b/);
	});

	it('没有十六进制与 rgb/a 字面色', () => {
		expect(code).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
		expect(code).not.toMatch(/\brgba?\(/);
		expect(code).not.toMatch(/\bhsla?\(/);
	});

	it('没有 Tailwind 调色板字面量（一切前景/底色走 --xy 令牌）', () => {
		expect(code).not.toMatch(
			/\b(?:bg|text|border|fill|stroke|from|to)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/,
		);
	});

	it('图表/槽位用色必须是 var(--xy-*) 令牌（内联色字面量不得是十六进制/rgb/hsl）', () => {
		// 收集源码里所有「直接引号包起来的颜色值」：CSS 变量引用或十六进制/rgb/hsl 字面量。
		// 小时槽位图把 `background: cond ? 'var(--xy-chart)' : 'var(--xy-line)'` 写成三元，
		// 用 `color:/background:` 前缀抓不到；这里改抓字符串字面量本身，覆盖面更大。
		const literals = [
			...code.matchAll(
				/['"](var\(--[^'"]+\)|#[0-9a-fA-F]{3,8}|rgba?\([^'"]+\)|hsla?\([^'"]+\))['"]/g,
			),
		].map(m => m[1] ?? '');
		expect(literals.length).toBeGreaterThan(0);
		for (const value of literals) expect(value).toMatch(/^var\(--xy-/);
	});
});

/**
 * 容器那层的两条错误态（在这里测而不是只放 A3SnapshotPanel.test.tsx 的原因：
 * "报告还没生成"与"数据面读不出"是这整个特性最容易被糊弄过去的两个分支，
 * 而它们**不属于**视图组件——视图只收到已经裁好的 payload。
 */
describe('数据面失败时容器怎么说', () => {
	it('报告还没生成：不发数据请求，只说"尚未生成报告"', async () => {
		reportMock.mockResolvedValue({
			ok: true,
			data: {
				ok: false,
				exists: false,
				path: 'D:/docs/A3-monitor.html',
				url: 'file:///D:/docs/A3-monitor.html',
			},
			message: '',
		});
		dataMock.mockResolvedValue({ok: false, data: null, message: 'not_found'});

		render(<A3SnapshotPanel active />);

		await screen.findByText('尚未生成报告');
		expect(screen.queryByText(/报告数据读不出来/)).toBeNull();
		expect(dataMock).not.toHaveBeenCalled();
	});

	it('数据面 500：退回 iframe，并把原因写成中文', async () => {
		reportMock.mockResolvedValue({
			ok: true,
			data: {
				ok: true,
				exists: true,
				path: 'D:/docs/A3-monitor.html',
				url: 'file:///D:/docs/A3-monitor.html',
				bytes: 10_629_939,
				mtime: 1,
				generated_at: '2026-09-27T18:31:19.658759+00:00',
				days: ['2026-09-27'],
			},
			message: '',
		});
		dataMock.mockResolvedValue({
			ok: false,
			data: null,
			message: 'memory_report_unparsable',
		});

		render(<A3SnapshotPanel active />);

		expect(await screen.findByTitle('A3 日常监控报告')).toBeInTheDocument();
		expect(screen.getByText('报告数据读不出来（报告里的内嵌数据解析失败）')).toBeInTheDocument();
		expect(screen.queryByText('请求 · 小时分布')).toBeNull();
	});
});
