/**
 * A3NativePanel.test.tsx — 用量页看板的四条硬账（数据源=实时账本）。
 *
 * 1. KPI 逐个来自 payload，缺字段就说"数据里没有"，不补 0、不画假柱；
 * 2. `accepted` 是服务端的验收判据，界面**只展示**：fixture 特意让"数据很好但未验收"
 *    与"数据残缺但已验收"同时存在——只要界面从数字反推判据，这两条就会互相打脸；
 *    实时账本还有第三种"从没快照过" ⇒ 必须说"未快照"，不许退成前两种；
 * 3. 账本里没有这一天 / 读不出，界面说的话要和证据一致（容器那层负责，见
 *    A3SnapshotPanel.test.tsx）；
 * 4. 颜色全部走主题令牌，源码里不许出现写死色（这条把"不再是贴进来的网页"钉成机器判据，
 *    扫描面覆盖用量页这一族全部新文件）。
 *
 * fixture 全部是确定值：不读时钟、不读 locale（聚合时刻只做存在性断言，不比字符串）。
 */
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';

const dayMock = vi.fn();
const reportMock = vi.fn();
const liveMock = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		fetchLiveUsageDay: (day: string) => dayMock(day),
		fetchLiveUsageReport: () => liveMock(),
		getMemoryReport: () => reportMock(),
		runMemorySnapshot: vi.fn(),
		memoryReportViewUrl: () => 'http://127.0.0.1:8000/v1/settings/memory/report/view',
	};
});

vi.mock('@/lib/toast', () => ({
	toast: {error: vi.fn(), success: vi.fn()},
}));

// jsdom 没有 ResizeObserver，而用量页共用的 UsageChart 用它量容器宽度。
class ResizeObserverStub {
	observe(): void {}
	unobserve(): void {}
	disconnect(): void {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub);

/* eslint-disable import/first */
import {A3NativePanel} from './A3NativePanel';
import type {LiveUsageReport} from '@/lib/api';

/** 24 桶：只在 09 点挂 n 笔，其余为 0。 */
const hours = (n: number, at = 9) =>
	Array.from({length: 24}, (_, i) => (i === at ? n : 0));

const DAY_OK: LiveUsageReport['days'][number] = {
	day: '2026-09-27',
	// 数据很漂亮，但快照判它未验收：界面必须跟着判据说"待验收"。
	accepted: false,
	requests: 42,
	prompt_tokens: 1_200_000,
	cache_hit: 950_000,
	cache_miss: 50_000,
	hit_rate: 0.95,
	c2_count: 3,
	output: 9_000,
	tokens: 1_209_000,
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

const DAY_HOLES: LiveUsageReport['days'][number] = {
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
	tokens: null,
	cost_cny: null,
	sessions: 7,
	turns: 20,
	hour_counts: hours(20, 3),
	hour_unknown: 2,
	by_model: [],
};

const DATA: LiveUsageReport = {
	ok: true,
	live: true,
	generated_at: '2026-09-28T18:31:19+08:00',
	source: {kind: 'live_ledger', path: 'C:/Users/me/.xeyo/usage/events.jsonl', rows: 1234, store: 'ok'},
	day_count: 2,
	days: [DAY_OK, DAY_HOLES],
};

/**
 * 一天里混了「无价目」行：合计仍是数字（只累加有价行），但必须自报「部分未知」；
 * 无价目的模型行单独说「无价目」，绝不显示 ¥0.00。
 */
const DAY_MIXED_PRICE: LiveUsageReport['days'][number] = {
	day: '2026-09-29',
	accepted: true,
	requests: 50,
	prompt_tokens: 100_000,
	cache_hit: 40_000,
	cache_miss: 60_000,
	hit_rate: 0.4,
	c2_count: 0,
	output: 1_000,
	tokens: 101_000,
	cost_cny: 2.0,
	cost_unknown_requests: 3,
	sessions: 1,
	turns: 2,
	hour_counts: hours(2, 3),
	hour_unknown: 0,
	by_model: [
		{
			provider: 'zhipu',
			model: 'XenYon/glm-4.6v',
			requests: 3,
			prompt_tokens: 1_000,
			cache_hit: 0,
			cache_miss: 1_000,
			hit_rate: 0,
			output: 10,
			cost_cny: null,
			cost_unknown_requests: 3,
		},
		{
			provider: 'deepseek',
			model: 'XenYon/deepseek-v4-flash',
			requests: 47,
			prompt_tokens: 99_000,
			cache_hit: 40_000,
			cache_miss: 59_000,
			hit_rate: 0.4,
			output: 990,
			cost_cny: 2.0,
		},
	],
};

/** 从没进过快照的一天：判据是 null，界面要说"未快照"，不许退成"待验收"。 */
const DAY_NO_SNAPSHOT: LiveUsageReport['days'][number] = {
	...DAY_OK,
	day: '2026-09-30',
	accepted: null,
	snapshot: false,
};

const kpiText = (container: HTMLElement, label: string) =>
	container.querySelector(`[data-a3-kpi="${label}"]`)?.textContent ?? '';

beforeEach(() => {
	dayMock.mockReset();
	reportMock.mockReset();
	liveMock.mockReset();
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
		// 既有报告布局把 C2 放在运行记录，KPI 第八项为轮次。
		expect(kpiText(container, '轮次')).toContain('20');
		expect(container.querySelector('.xy-a3-c2')).toHaveTextContent('C2 事件：0');
		expect(kpiText(container, '会话数')).toContain('7');
		// 0 是真值：不许把它当成缺失渲染成"数据里没有"。
		expect(container.querySelector('.xy-a3-c2')).not.toHaveTextContent('数据里没有');
	});

	it('缺字段的 KPI 直说"数据里没有"；账上明写无价目时说"无价目"（都是缺失，但不是 0）', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		expect(kpiText(container, '请求')).toContain('数据里没有');
		// cost_cny: null 是上游核实过「没有权威价目」，不是「这一层没读到字段」，
		// 更不能落成 ¥0.00（那会把费用未知读成免费）。
		expect(kpiText(container, '成本')).toContain('无价目');
		expect(kpiText(container, '成本')).not.toContain('¥');
		expect(kpiText(container, '单位成本')).toContain('无价目');
	});

	it('切到数据完整的一天：KPI 与分模型表跟着换', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的日期'}), {
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
		// 模型名同时出现在过滤 chip、环形卡明细与分模型表里：只断言「至少三处」。
		expect(screen.getAllByText('deepseek-v4-flash').length).toBeGreaterThanOrEqual(3);
	});

	it('混了无价目行：合计标"部分未知"，无价目那一行说"无价目"而不是 ¥0.00', () => {
		const {container} = render(
			<A3NativePanel data={{...DATA, days: [DAY_MIXED_PRICE]}} />,
		);

		expect(kpiText(container, '成本')).toContain('¥2.00');
		expect(kpiText(container, '成本')).toContain('部分未知');
		expect(kpiText(container, '单位成本')).toContain('部分未知');
		// 无价目模型行：没有金额就说没有，不写 ¥0.00、不写空串、不留白。
		expect(screen.getAllByText('无价目').length).toBeGreaterThan(0);
		expect(screen.queryByText('¥0.00')).toBeNull();
	});

	it('无时间戳的轮数要说出来，不静默丢', () => {
		render(<A3NativePanel data={DATA} />);

		expect(screen.getByText(/2 轮无时间戳，未计入/)).toBeInTheDocument();
	});

	it('输入 token 的缓存构成条复用 usageSegments：有数据才画', () => {
		const {container} = render(<A3NativePanel data={DATA} />);

		// 默认选中的那天 hit/miss 都是 null ⇒ 不画（宽度钳制会把它画成假的五五分）。
		expect(container.querySelector('[data-a3-hitmiss]')).toBeNull();

		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的日期'}), {
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
	it('formatMoney：≥¥1 两位、0<¥1 四位、恰好 0 用两位', async () => {
		const {formatMoney} = await import('@/lib/formatUsage');
		expect(formatMoney(18.764621)).toBe('¥18.76');
		expect(formatMoney(5.844108)).toBe('¥5.84');
		expect(formatMoney(0.013312)).toBe('¥0.0133');
		expect(formatMoney(0)).toBe('¥0.00');
	});

	it('KPI 渲染按量级给精度：总额两位、单位成本四位', () => {
		const {container} = render(<A3NativePanel data={DATA} />);
		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的日期'}), {
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
		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的日期'}), {
			target: {value: DAY_OK.day},
		});

		// DAY_OK：命中 950000 / 输入 950000+50000=1000000。
		expect(screen.getByText('950.00k / 1.00M')).toBeInTheDocument();
		expect(screen.queryByText(/950,000/)).toBeNull();
	});
});

describe('验收判据只透传（三态）', () => {
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

	it('三态各说各话：已验收 / 待验收 / 未快照，不许由数字反推', () => {
		const days = [DAY_OK, DAY_HOLES, DAY_NO_SNAPSHOT];
		render(<A3NativePanel data={{...DATA, days, day_count: days.length}} />);

		// 数据漂亮但未验收 ⇒ 待验收；数据残缺但已验收 ⇒ 已验收；null ⇒ 未快照。
		expect(screen.getAllByText('待验收')).toHaveLength(1);
		expect(screen.getAllByText('已验收')).toHaveLength(1);
		// 顶栏跟着选中那天（最后一天=未快照）⇒ 未快照两处：顶栏 + 它自己那一行。
		// 顶栏那行是「快照状态：未快照」的连续文本，exact 匹配只命中表格里它自己那一行。
		expect(screen.getByText(/快照状态：未快照/)).toBeInTheDocument();
		expect(screen.getAllByText('未快照')).toHaveLength(1);
		// 判据要钉在**它自己那一天**上：串了行就等于界面自己算了一个判据。
		expect(screen.getByText('待验收').closest('tr')?.textContent).toContain(DAY_OK.day);
		expect(screen.getByText('已验收').closest('tr')?.textContent).toContain(DAY_HOLES.day);
	});

	it('顶栏状态跟着选中那天走', () => {
		render(<A3NativePanel data={DATA} />);

		expect(screen.getByText(/快照状态：已验收/)).toBeInTheDocument();

		fireEvent.change(screen.getByRole('combobox', {name: '选择查看的日期'}), {
			target: {value: DAY_OK.day},
		});

		expect(screen.getByText(/快照状态：待验收/)).toBeInTheDocument();
	});
});

describe('诚实的空态', () => {
	it('账本里没有任何一天：明说，不画空图、不摆 0 值 KPI', () => {
		const {container} = render(
			<A3NativePanel data={{...DATA, day_count: 0, days: []}} />,
		);

		expect(screen.getByText('账本里还没有任何一天的数据。')).toBeInTheDocument();
		expect(container.querySelector('[data-a3-kpi="命中率"]')).toBeNull();
		expect(screen.queryByText('活动分布 · 每小时轮次')).toBeNull();
	});

	it('分模型行为空时说"没有分模型行"，不渲染空表头当作有数据', () => {
		render(<A3NativePanel data={DATA} />);

		expect(screen.getByText('这一天没有分模型行。')).toBeInTheDocument();
	});
});

describe('模型过滤只影响环形卡与分模型表', () => {
	it('选中一个模型：分模型表只剩它，KPI 仍是全口径', () => {
		const {container} = render(
			<A3NativePanel data={{...DATA, days: [DAY_MIXED_PRICE], day_count: 1}} />,
		);
		fireEvent.click(screen.getByRole('button', {name: /glm-4\.6v/}));

		const models = container.querySelector('[data-a3-models]')?.textContent ?? '';
		expect(models).not.toContain('deepseek-v4-flash');
		expect(models).toContain('glm-4.6v');
		// KPI 不受过滤影响：请求仍是 50，不是 3。
		expect(kpiText(container, '请求')).toContain('50');
	});

	it('取消选择回到全部', () => {
		const {container} = render(
			<A3NativePanel data={{...DATA, days: [DAY_MIXED_PRICE], day_count: 1}} />,
		);
		fireEvent.click(screen.getByRole('button', {name: /glm-4\.6v/}));
		fireEvent.click(screen.getByRole('button', {name: '全部'}));

		const models = container.querySelector('[data-a3-models]')?.textContent ?? '';
		expect(models).toContain('deepseek-v4-flash');
		expect(models).toContain('glm-4.6v');
	});
});

describe('会话明细：一次请求换一天', () => {
	it('展开时才发请求，且只发选中那一天', async () => {
		dayMock.mockResolvedValue({
			ok: true,
			message: '',
			data: {
				ok: true,
				live: true,
				generated_at: DATA.generated_at,
				source: DATA.source,
				day: DAY_HOLES.day,
				missing: false,
				summary: DAY_HOLES,
				sessions: [
					{
						session_id: 'sess_x',
						requests: 5,
						prompt_tokens: 1000,
						cache_hit: 900,
						cache_miss: 100,
						hit_rate: 0.9,
						output: 40,
						cost_cny: 0.02,
					},
				],
				turns: [
					{
						session_id: 'sess_x',
						label: '把压缩器接回主链',
						model: 'deepseek-v4-flash',
						first_ts: 1_788_672_364.839,
						requests: 5,
						prompt_tokens: 1000,
						cache_hit: 900,
						cache_miss: 100,
						hit_rate: 0.9,
						output: 40,
						cost_cny: 0.02,
						event_count: 2,
						events_truncated: 0,
						events: [
							{ts: 1_788_672_364.839, model: 'deepseek-v4-flash', cache_hit: 800, cache_miss: 100, output: 20, prompt_tokens: 900, cost_cny: 0.01},
							{ts: 1_788_672_400.111, model: 'deepseek-v4-flash', cache_hit: 100, cache_miss: 0, output: 20, prompt_tokens: 100, cost_cny: 0.01},
						],
					},
				],
				events_truncated: 0,
			},
		});
		render(<A3NativePanel data={DATA} />);
		expect(dayMock).not.toHaveBeenCalled();

		fireEvent.click(screen.getByRole('button', {name: '查看会话明细'}));

		expect(await screen.findByText('把压缩器接回主链')).toBeInTheDocument();
		expect(dayMock).toHaveBeenCalledWith(DAY_HOLES.day);
		// 每枪一行：展开后能看到该轮两次模型调用各自的时间。
		fireEvent.click(screen.getByRole('button', {name: /把压缩器接回主链/}));
		// 该轮 2 次模型调用各自一行（重试 attempt 也各占一行，与账本 S4 口径一致）。
		expect(document.querySelectorAll('[data-a3-event-row]')).toHaveLength(2);
	});
});

describe('不出现写死颜色（扫描用量页这一族全部文件）', () => {
	// 搬家/新增文件必须同时进这张清单：只扫旧文件会让新文件静默失去覆盖面。
	const FILES = [
		'src/components/A3NativePanel.tsx',
		'src/components/A3SnapshotPanel.tsx',
		'src/components/review/A3DayNavigator.tsx',
		'src/components/usage/TokenActivityHeatmap.tsx',
		'src/components/usage/DonutCard.tsx',
		'src/components/usage/ModelTable.tsx',
		'src/components/usage/TurnDrilldown.tsx',
		'src/components/usage/palette.ts',
	];
	const code = FILES.map(f =>
		readFileSync(resolve(process.cwd(), f), 'utf8')
			.replace(/\/\*[\s\S]*?\*\//g, '')
			.split('\n')
			.filter(l => !/^\s*(\/\/|\*)/.test(l))
			.join('\n'),
	);

	it('扫描面本身有效（防止文件读空导致断言空跑）', () => {
		expect(FILES).toHaveLength(8);
		for (const src of code) expect(src.length).toBeGreaterThan(80);
		expect(code[0]).toContain('var(--xy-chart)');
	});

	it('没有 bg-white / text-white', () => {
		for (const src of code) {
			expect(src).not.toMatch(/\bbg-white\b/);
			expect(src).not.toMatch(/\btext-white\b/);
		}
	});

	it('没有十六进制与 rgb/a 字面色', () => {
		for (const src of code) {
			expect(src).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
			expect(src).not.toMatch(/\brgba?\(/);
			expect(src).not.toMatch(/\bhsla?\(/);
		}
	});

	it('没有 Tailwind 调色板字面量（一切前景/底色走 --xy 令牌）', () => {
		for (const src of code) {
			expect(src).not.toMatch(
				/\b(?:bg|text|border|fill|stroke|from|to)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/,
			);
		}
	});

	it('图表/槽位用色必须是 var(--xy-*) 令牌（内联色字面量不得是十六进制/rgb/hsl）', () => {
		for (const src of code) {
			const literals = [
				...src.matchAll(
					/['"`](var\(--[^'"`]+\)|#[0-9a-fA-F]{3,8}|rgba?\([^'"`]+\)|hsla?\([^'"`]+\))['"`]/g,
				),
			].map(m => m[1] ?? '');
			for (const value of literals) expect(value).toMatch(/^var\(--xy-/);
		}
	});
});
