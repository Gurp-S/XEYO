/**
 * A3SnapshotPanel.test.tsx — 用量页主面的三种读数必须分家，外加"数据面 vs iframe 兜底"。
 *
 * "报告存在" / "后端确认还没生成" / "我们没读到" 是三件事。
 * 客户端原来把后两种压成 null，面板于是对着一次 403 说"还没有 A3 快照"。
 *
 * 2026-09-28 起，报告存在且数据面可读时界面**原生渲染**（不再有 iframe）；只有
 * `/report/data` 读不出来才退回 iframe，并且必须写明退的原因。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';

const reportMock = vi.fn();
const dataMock = vi.fn();
const dayMock = vi.fn();
const snapshotMock = vi.fn();
const toastError = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		getMemoryReport: () => reportMock(),
		getMemoryReportData: () => dataMock(),
		getMemoryReportDay: (day: string) => dayMock(day),
		runMemorySnapshot: () => snapshotMock(),
		memoryReportViewUrl: () => 'http://127.0.0.1:8000/v1/settings/memory/report/view',
	};
});

vi.mock('@/lib/openExternal', () => ({openExternalUrl: vi.fn(async () => {})}));
vi.mock('@/lib/toast', () => ({
	toast: {error: (...args: unknown[]) => toastError(...args), success: vi.fn()},
}));

// jsdom 没有 ResizeObserver，而原生视图里的 UsageChart 用它量宽度。
class ResizeObserverStub {
	observe(): void {}
	unobserve(): void {}
	disconnect(): void {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub);

/* eslint-disable import/first */
import {A3SnapshotPanel} from './A3SnapshotPanel';

const EXISTS = {
	ok: true,
	exists: true,
	path: 'D:/docs/A3-monitor.html',
	url: 'file:///D:/docs/A3-monitor.html',
	bytes: 4096,
	mtime: 1,
	generated_at: '2026-09-24T09:30:00',
	days: ['2026-09-23', '2026-09-24'],
};

/** 24 桶里只有 09 点有 n 笔，其余为 0。 */
const hoursWith = (n: number) => Array.from({length: 24}, (_, i) => (i === 9 ? n : 0));

const DATA = {
	ok: true as const,
	generated_at: '2026-09-27T17:47:02+00:00',
	source: {path: 'D:/docs/A3-monitor.html', bytes: 10_415_940, mtime: 1},
	day_count: 2,
	days: [
		{
			day: '2026-09-23',
			accepted: false,
			requests: 100,
			prompt_tokens: 400_000,
			cache_hit: 300_000,
			cache_miss: 100_000,
			hit_rate: 0.75,
			c2_count: 3,
			output: 1200,
			cost_cny: 1.25,
			sessions: 4,
			turns: 9,
			hour_counts: hoursWith(9),
			hour_unknown: 0,
			by_model: [
				{
					provider: 'openai',
					model: 'XenYon/deepseek-v4-flash',
					requests: 100,
					prompt_tokens: 400_000,
					cache_hit: 300_000,
					cache_miss: 100_000,
					hit_rate: 0.75,
					output: 1200,
					cost_cny: 1.25,
				},
			],
		},
		{
			// requests 后端回了 null：界面必须说"数据里没有"，不许补 0 也不许画横杠。
			day: '2026-09-24',
			accepted: true,
			requests: null,
			prompt_tokens: 200_000,
			cache_hit: 150_000,
			cache_miss: 50_000,
			hit_rate: 0.75,
			c2_count: 0,
			output: 900,
			cost_cny: 0.5,
			sessions: 2,
			turns: 5,
			hour_counts: hoursWith(5),
			hour_unknown: 1,
			by_model: [],
		},
	],
};

const DAY_DETAIL = {
	ok: true as const,
	generated_at: '2026-09-27T17:47:02+00:00',
	source: {path: 'D:/docs/A3-monitor.html', bytes: 10_415_940, mtime: 1},
	day: '2026-09-24',
	summary: DATA.days[1],
	sessions: [
		{
			session_id: 'pov-ray__Wk2DcsZ__agent',
			requests: 54,
			prompt_tokens: 397_928,
			cache_hit: 356_352,
			cache_miss: 41_576,
			hit_rate: 0.8955,
			output: 143_857,
			cost_cny: 0.727538,
		},
	],
	turns: [
		{
			session_id: 'pov-ray__52qKAhM__agent',
			label: 'Build POV-Ray 2.2. Find and download the…',
			model: 'deepseek-v4-flash',
			requests: 6,
			cache_hit: 9088,
			cache_miss: 3360,
			hit_rate: 0.7301,
			output: 1052,
			cost_cny: 0.010228,
			first_ts: 1_788_672_364.839,
			event_count: 6,
		},
	],
};

beforeEach(() => {
	reportMock.mockReset();
	dataMock.mockReset();
	dayMock.mockReset();
	snapshotMock.mockReset();
	toastError.mockReset();
	// 默认：数据面读不出来 ⇒ 走 iframe 兜底（旧断言口径不变）。
	dataMock.mockResolvedValue({ok: false, data: null, message: 'receipt_bad_report_data'});
});

afterEach(() => {
	cleanup();
});

describe('报告状态', () => {
	it('读不出：写明原因，且不出现"还没有 A3 快照"', async () => {
		reportMock.mockResolvedValue({ok: false, data: null, message: 'loopback only'});

		render(<A3SnapshotPanel active />);

		await waitFor(() =>
			expect(screen.getByText(/未读到 A3 报告状态（loopback only）/)).toBeTruthy(),
		);
		expect(screen.queryByText(/还没有 A3 快照/)).toBeNull();
		expect(screen.getByRole('button', {name: '新窗口'})).toBeDisabled();
	});

	it('后端确认还没生成：才允许说"尚未生成报告"', async () => {
		reportMock.mockResolvedValue({
			ok: true,
			data: {ok: false, exists: false, path: 'D:/docs/A3-monitor.html', url: ''},
			message: '',
		});

		render(<A3SnapshotPanel active />);

		await waitFor(() => expect(screen.getByText('尚未生成报告')).toBeTruthy());
		expect(screen.getByText(/还没有 A3 快照/)).toBeTruthy();
	});

	it('报告存在：头部给文件名 / 天数 / 大小', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});

		render(<A3SnapshotPanel active />);

		await waitFor(() => expect(screen.getByText(/A3-monitor\.html/)).toBeTruthy());
		expect(screen.getByText(/2 天/)).toBeTruthy();
		expect(screen.getByText(/4 KB/)).toBeTruthy();
		expect(screen.getByRole('button', {name: '新窗口'})).not.toBeDisabled();
	});

	it('数据可读：原生渲染，不再挂 iframe', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		dataMock.mockResolvedValue({ok: true, data: DATA, message: ''});

		render(<A3SnapshotPanel active />);

		await screen.findByText('请求 · 小时分布');
		expect(screen.queryByTitle('A3 日常监控报告')).toBeNull();
		expect(screen.getByText('分模型')).toBeTruthy();
		expect(screen.getByText('每日快照')).toBeTruthy();
		// 选中的是最后一天（集合里最后一天 = 2026-09-24），KPI 跟着它走。
		expect(screen.getByRole('combobox', {name: '选择查看的快照日期'})).toHaveValue(
			'2026-09-24',
		);
	});

	it('数据里没有的 KPI：直说"数据里没有"，不补 0 也不静默画横杠', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		dataMock.mockResolvedValue({ok: true, data: DATA, message: ''});

		const {container} = render(<A3SnapshotPanel active />);

		await screen.findByText('请求 · 小时分布');
		// 2026-09-24 的 requests 是 null ⇒ 请求 KPI 与单位成本都不能编出数来。
		expect(container.querySelector('[data-a3-kpi="请求"]')?.textContent).toContain(
			'数据里没有',
		);
		expect(container.querySelector('[data-a3-kpi="单位成本"]')?.textContent).toContain(
			'数据里没有',
		);
		// c2_count = 0 是真值，不该被当成缺失。
		expect(container.querySelector('[data-a3-kpi="C2"]')?.textContent).toContain('0');
		// 有分母的命中率照算：150000/(150000+50000) = 75.0
		expect(screen.getAllByText('75.0%').length).toBeGreaterThanOrEqual(1);
	});

	it('点"查看会话明细"只取那一天', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		dataMock.mockResolvedValue({ok: true, data: DATA, message: ''});
		dayMock.mockResolvedValue({ok: true, data: DAY_DETAIL, message: ''});

		render(<A3SnapshotPanel active />);

		await screen.findByText('请求 · 小时分布');
		fireEvent.click(screen.getByRole('button', {name: '查看会话明细'}));

		await screen.findByText('按轮次（一条用户消息一行）');
		await waitFor(() => expect(dayMock).toHaveBeenCalledWith('2026-09-24'));
		expect(screen.getByText(/Build POV-Ray 2\.2/)).toBeTruthy();
		expect(screen.getByText(/1 个会话 · 1 轮/)).toBeTruthy();
	});

	it('数据读不出：退回 iframe，并写明为什么是网页', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		dataMock.mockResolvedValue({
			ok: false,
			data: null,
			message: 'memory_report_unparsable',
		});

		render(<A3SnapshotPanel active />);

		const frame = await screen.findByTitle('A3 日常监控报告');
		expect(frame).toBeTruthy();
		expect(screen.getByText('报告数据读不出来（报告里的内嵌数据解析失败）')).toBeTruthy();
		expect(screen.queryByText('请求 · 小时分布')).toBeNull();
	});

	it('报告还没生成时数据面 404：只说"尚未生成"，不说读不出来', async () => {
		reportMock.mockResolvedValue({
			ok: true,
			data: {...EXISTS, exists: false},
			message: '',
		});
		dataMock.mockResolvedValue({ok: false, data: null, message: 'not_found'});

		render(<A3SnapshotPanel active />);

		await waitFor(() => expect(screen.getByText('尚未生成报告')).toBeTruthy());
		expect(screen.queryByText(/报告数据读不出来/)).toBeNull();
		// 报告不存在时数据面根本不该发请求（免得拿一个 404 回来当故障说）。
		expect(dataMock).not.toHaveBeenCalled();
	});

	it('刷新按钮会重读一次', async () => {
		reportMock
			.mockResolvedValueOnce({ok: false, data: null, message: 'HTTP 503'})
			.mockResolvedValueOnce({ok: true, data: EXISTS, message: ''});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/HTTP 503/);

		fireEvent.click(screen.getByRole('button', {name: '刷新 A3 报告状态'}));

		await waitFor(() => expect(reportMock).toHaveBeenCalledTimes(2));
		await waitFor(() => expect(screen.getByText(/A3-monitor\.html/)).toBeTruthy());
		expect(screen.queryByText(/未读到 A3 报告状态/)).toBeNull();
	});
});

describe('立即快照', () => {
	it('读不到回执时说"未确认"，不说"失败"', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		snapshotMock.mockResolvedValue({ok: false, data: null, message: 'Failed to fetch'});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/A3-monitor\.html/);

		fireEvent.click(screen.getByRole('button', {name: '立即快照'}));

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		const msg = String(toastError.mock.calls[0][0]);
		expect(msg).toContain('未确认');
		expect(msg).not.toContain('A3 快照失败');
	});

	it('后端自报失败时用它的原话', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		snapshotMock.mockResolvedValue({
			ok: true,
			data: {ok: false, error: '生成器退出码 1'},
			message: '',
		});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/A3-monitor\.html/);

		fireEvent.click(screen.getByRole('button', {name: '立即快照'}));

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(String(toastError.mock.calls[0][0])).toContain('生成器退出码 1');
	});

	it('补齐多天成功后写清补齐范围，并刷新报告', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		snapshotMock.mockResolvedValue({
			ok: true,
			data: {ok: true, days: ['2026-09-20', '2026-09-21', '2026-09-22']},
			message: '',
		});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/A3-monitor\.html/);

		fireEvent.click(screen.getByRole('button', {name: '立即快照'}));

		await waitFor(() =>
			expect(screen.getByText(/补齐 3 天（2026-09-20 → 2026-09-22）/)).toBeTruthy(),
		);
		expect(reportMock).toHaveBeenCalledTimes(2);
	});
});
