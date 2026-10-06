/**
 * A3SnapshotPanel.test.tsx — 用量页容器的读数分家。
 *
 * 主面是**实时账本**（`GET /v1/usage/report`），快照降级成"生成网页报告"这个次要动作。
 * 于是三组读数必须各说各话：
 *
 * 1. 账本：读不出（HTTP 失败 / 形状变了）≠ 本机还没有记录（store=missing_store 是
 *    后端给得出的正面答案）；读不出时**不许**退回快照报告——那等于用一份可能过期的
 *    数据冒充"读到了"。
 * 2. 快照状态：读不出 / 尚未生成 / 已生成 三态，按钮只认后端明确给的 exists。
 * 3. 快照回执：读不到回执说"未确认"，后端自报失败用它的原话。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';

const reportMock = vi.fn();
const liveMock = vi.fn();
const dayMock = vi.fn();
const snapshotMock = vi.fn();
const toastError = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		getMemoryReport: () => reportMock(),
		fetchLiveUsageReport: () => liveMock(),
		fetchLiveUsageDay: (day: string) => dayMock(day),
		runMemorySnapshot: () => snapshotMock(),
		memoryReportViewUrl: () => 'http://127.0.0.1:8000/v1/settings/memory/report/view',
	};
});

vi.mock('@/lib/openExternal', () => ({openExternalUrl: vi.fn(async () => {})}));
vi.mock('@/lib/toast', () => ({
	toast: {error: (...args: unknown[]) => toastError(...args), success: vi.fn()},
}));

// jsdom 没有 ResizeObserver，而用量页共用的 UsageChart 用它量宽度。
class ResizeObserverStub {
	observe(): void {}
	unobserve(): void {}
	disconnect(): void {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub);

/* eslint-disable import/first */
import {A3SnapshotPanel} from './A3SnapshotPanel';

const SNAP_EXISTS = {
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

const LIVE = {
	ok: true as const,
	live: true as const,
	generated_at: '2026-09-28T17:47:02+08:00',
	source: {
		kind: 'live_ledger',
		path: 'C:/Users/me/.xeyo/usage/events.jsonl',
		rows: 18_283,
		store: 'ok',
		bytes: 7_318_621,
		mtime: 1,
	},
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
			tokens: 401_200,
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
			accepted: null,
			requests: null,
			prompt_tokens: 200_000,
			cache_hit: 150_000,
			cache_miss: 50_000,
			hit_rate: 0.75,
			c2_count: 0,
			output: 900,
			tokens: 200_900,
			cost_cny: 0.5,
			sessions: 2,
			turns: 5,
			hour_counts: hoursWith(5),
			hour_unknown: 1,
			by_model: [],
		},
	],
};

beforeEach(() => {
	reportMock.mockReset();
	liveMock.mockReset();
	dayMock.mockReset();
	snapshotMock.mockReset();
	toastError.mockReset();
	// 默认：快照状态读不出（与"没有快照"分开），实时账本可读。
	reportMock.mockResolvedValue({ok: false, data: null, message: 'receipt_bad_report'});
	liveMock.mockResolvedValue({ok: true, data: LIVE, message: ''});
});

afterEach(() => {
	cleanup();
});

describe('实时账本读数', () => {
	it('可读：原生渲染，页面上不再有 iframe', async () => {
		render(<A3SnapshotPanel active />);

		await screen.findByText('活动分布 · 每小时轮次');
		expect(screen.queryByTitle('A3 日常监控报告')).toBeNull();
		expect(screen.getByText('分模型')).toBeTruthy();
		expect(screen.getByText('Token 活动')).toBeTruthy();
		expect(screen.getByText(/18,283 笔用量记录/)).toBeTruthy();
		// 选中的是最后一天（集合里最后一天 = 2026-09-24），KPI 跟着它走。
		expect(screen.getByRole('combobox', {name: '选择查看的日期'})).toHaveValue('2026-09-24');
	});

	it('读不出：写明原因，且不说"本机还没有用量记录"', async () => {
		liveMock.mockResolvedValue({ok: false, data: null, message: 'loopback only'});

		render(<A3SnapshotPanel active />);

		await screen.findByText(/没读到本机用量账本（loopback only）/);
		expect(screen.queryByText(/本机还没有用量记录/)).toBeNull();
		// 读不出不退回快照报告：宁可空着并给原因，也不拿旧快照冒充最新。
		expect(screen.queryByTitle('A3 日常监控报告')).toBeNull();
	});

	it('账本里没有记录（后端确认 missing_store）：说"还没有用量记录"，不是故障', async () => {
		liveMock.mockResolvedValue({
			ok: true,
			message: '',
			data: {...LIVE, day_count: 0, days: [], source: {...LIVE.source, rows: 0, store: 'missing_store'}},
		});

		render(<A3SnapshotPanel active />);

		await screen.findByText(/本机还没有用量记录/);
		expect(screen.queryByText(/没读到/)).toBeNull();
	});

	it('数据里没有的 KPI：直说"数据里没有"，不补 0 也不静默画横杠', async () => {
		const {container} = render(<A3SnapshotPanel active />);

		await screen.findByText('活动分布 · 每小时轮次');
		// 2026-09-24 的 requests 是 null ⇒ 请求 KPI 与单位成本都不能编出数来。
		expect(container.querySelector('[data-a3-kpi="请求"]')?.textContent).toContain('数据里没有');
		expect(container.querySelector('[data-a3-kpi="单位成本"]')?.textContent).toContain('数据里没有');
		// c2_count = 0 是真值，不该被当成缺失。
		expect(container.querySelector('.xy-a3-c2')).toHaveTextContent('C2 事件：0');
		// 有分母的命中率照算：150000/(150000+50000) = 75.0
		expect(screen.getAllByText('75.0%').length).toBeGreaterThanOrEqual(1);
		// 这一天从没进过快照 ⇒ 判据是"未快照"，不是"待验收"。
		expect(screen.getByText(/快照状态：未快照/)).toBeInTheDocument();
	});

	it('刷新按钮重读一次账本', async () => {
		liveMock
			.mockResolvedValueOnce({ok: false, data: null, message: 'HTTP 503'})
			.mockResolvedValue({ok: true, data: LIVE, message: ''});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/HTTP 503/);

		fireEvent.click(screen.getByRole('button', {name: '刷新用量数据'}));

		await waitFor(() => expect(liveMock).toHaveBeenCalledTimes(2));
		await screen.findByText('活动分布 · 每小时轮次');
		expect(screen.queryByText(/没读到本机用量账本/)).toBeNull();
	});

	it('active=false 时不发请求（页面切走不占后端）', () => {
		render(<A3SnapshotPanel active={false} />);
		expect(liveMock).not.toHaveBeenCalled();
		expect(reportMock).not.toHaveBeenCalled();
	});
});

describe('快照状态（降级为次要动作）', () => {
	it('报告已生成：状态行给文件名与天数，「新窗口」可用', async () => {
		reportMock.mockResolvedValue({ok: true, data: SNAP_EXISTS, message: ''});

		const {container} = render(<A3SnapshotPanel active />);

		await screen.findByText(/A3-monitor\.html/);
		// 快照状态行自己报天数；看板顶栏也有「2 天」（账本天数），两者不混为一谈。
		expect(
			container.querySelector('[data-a3-snapshot-status]')?.textContent,
		).toContain('2 天');
		expect(screen.getByRole('button', {name: '新窗口'})).not.toBeDisabled();
	});

	it('后端确认还没生成：说"尚未生成网页报告"，并说明不影响本页数据', async () => {
		reportMock.mockResolvedValue({
			ok: true,
			data: {ok: false, exists: false, path: 'D:/docs/A3-monitor.html', url: ''},
			message: '',
		});

		render(<A3SnapshotPanel active />);

		await screen.findByText(/尚未生成网页报告（不影响本页数据/);
		// 主面照常渲染：快照状态与账本读数分家。
		await screen.findByText('活动分布 · 每小时轮次');
		expect(screen.getByRole('button', {name: '新窗口'})).toBeDisabled();
	});

	it('状态读不出：写"未读到快照状态"，不退成"尚未生成"', async () => {
		reportMock.mockResolvedValue({ok: false, data: null, message: 'loopback only'});

		render(<A3SnapshotPanel active />);

		await screen.findByText(/未读到快照状态（loopback only）/);
		expect(screen.queryByText(/尚未生成网页报告/)).toBeNull();
	});
});

describe('生成网页报告（原「立即快照」）', () => {
	it('读不到回执时说"未确认"，不说"失败"', async () => {
		snapshotMock.mockResolvedValue({ok: false, data: null, message: 'Failed to fetch'});

		render(<A3SnapshotPanel active />);
		await screen.findByText('活动分布 · 每小时轮次');

		fireEvent.click(screen.getByRole('button', {name: '生成网页报告'}));

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		const msg = String(toastError.mock.calls[0][0]);
		expect(msg).toContain('未确认');
		expect(msg).not.toContain('A3 快照失败');
	});

	it('后端自报失败时用它的原话', async () => {
		snapshotMock.mockResolvedValue({
			ok: true,
			data: {ok: false, error: '生成器退出码 1'},
			message: '',
		});

		render(<A3SnapshotPanel active />);
		await screen.findByText('活动分布 · 每小时轮次');

		fireEvent.click(screen.getByRole('button', {name: '生成网页报告'}));

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(String(toastError.mock.calls[0][0])).toContain('生成器退出码 1');
	});

	it('补齐多天成功后写清补齐范围，并重读快照状态（不动主面数据）', async () => {
		reportMock.mockResolvedValue({ok: true, data: SNAP_EXISTS, message: ''});
		snapshotMock.mockResolvedValue({
			ok: true,
			data: {ok: true, days: ['2026-09-20', '2026-09-21', '2026-09-22']},
			message: '',
		});

		render(<A3SnapshotPanel active />);
		await screen.findByText('活动分布 · 每小时轮次');
		const before = liveMock.mock.calls.length;

		fireEvent.click(screen.getByRole('button', {name: '生成网页报告'}));

		await waitFor(() =>
			expect(screen.getByText(/网页报告 · 补齐 3 天（2026-09-20 → 2026-09-22）/)).toBeTruthy(),
		);
		// 快照只重读自己的状态；主面读数不该被它顺手刷掉。
		expect(reportMock).toHaveBeenCalledTimes(2);
		expect(liveMock).toHaveBeenCalledTimes(before);
	});
});
