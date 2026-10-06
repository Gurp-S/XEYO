/**
 * liveUsage.test.ts — 用量页实时数据面的客户端回执。
 *
 * 三条判据都来自这条通路的定位：它是"打开就是最新"的唯一来源，所以
 * 1. 后端确认"这一天没有记录"（missing:true）与"我们没读到"必须分家；
 * 2. 少给一个键 ⇒ 该键 null，不许退成 0（0 会被画成"这一天没跑"）；
 * 3. 后端说"有行"而 summary 形状读不出 ⇒ 算形状漂移（ok:false），不能当"没有"。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fetchLiveUsageDay, fetchLiveUsageReport} from '@/lib/api';

const fetchMock = vi.fn();

function response(payload: unknown, status = 200) {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => payload,
	};
}

const SUMMARY = {
	day: '2026-10-03',
	accepted: null,
	snapshot: false,
	requests: 19,
	prompt_tokens: 227_688,
	cache_hit: 79_009,
	cache_miss: 148_679,
	hit_rate: 0.347,
	c2_count: 1,
	output: 4773,
	tokens: 232_461,
	cost_cny: null,
	cost_unknown_requests: 19,
	sessions: 1,
	turns: 5,
	hour_counts: [0, 5, 0],
	hour_unknown: 0,
	unattributed_requests: 0,
	by_model: [{provider: 'deepseek', model: 'glm-4.6v', requests: 19, cost_cny: null}],
};

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('fetchLiveUsageReport', () => {
	it('带回日行与账本来源事实', async () => {
		fetchMock.mockResolvedValue(
			response({
				ok: true,
				live: true,
				generated_at: '2026-10-03T02:08:20+08:00',
				source: {kind: 'live_ledger', path: 'C:/u/.xeyo/usage/events.jsonl', rows: 18_283, store: 'ok'},
				day_count: 1,
				days: [SUMMARY],
			}),
		);

		const r = await fetchLiveUsageReport();

		expect(r.ok).toBe(true);
		expect(r.data?.days[0]?.day).toBe('2026-10-03');
		expect(r.data?.source.rows).toBe(18_283);
		expect(r.data?.source.store).toBe('ok');
		// 请求打到实时端点，不是快照报告那条路。
		expect(String(fetchMock.mock.calls[0][0])).toContain('/v1/usage/report');
	});

	it('缺键收成 null / undefined，不补 0；hour_counts 定长 24', async () => {
		fetchMock.mockResolvedValue(
			response({
				ok: true,
				live: true,
				generated_at: '',
				source: {},
				day_count: 1,
				days: [{day: '2026-10-03', accepted: false, requests: 3}],
			}),
		);

		const day = (await fetchLiveUsageReport()).data?.days[0];

		expect(day?.requests).toBe(3);
		expect(day?.cost_cny ?? null).toBeNull();
		expect(day?.tokens ?? null).toBeNull();
		expect(day?.hour_counts).toHaveLength(24);
		expect(day?.hour_counts[1]).toBe(0);
		expect(day?.by_model).toEqual([]);
	});

	it('HTTP 错误带回原因，不退化成"没有数据"', async () => {
		fetchMock.mockResolvedValue(
			response({error: {message: 'usage ledger unreadable', type: 'usage_ledger_unreadable'}}, 500),
		);

		const r = await fetchLiveUsageReport();

		expect(r.ok).toBe(false);
		expect(r.data).toBeNull();
		// 客户端把后端给的原因原样带回来（格式化后的 message），界面才有话可说。
		expect(r.message).toContain('usage ledger unreadable');
	});

	it('形状变了（days 不是数组）算没读到', async () => {
		fetchMock.mockResolvedValue(response({ok: true, days: {}}));
		const r = await fetchLiveUsageReport();
		expect(r.ok).toBe(false);
		expect(r.message).toContain('receipt_bad_live_usage');
	});

	it('fetch 抛错（离线）也回 ok:false 而不是崩', async () => {
		fetchMock.mockRejectedValue(new Error('Failed to fetch'));
		const r = await fetchLiveUsageReport();
		expect(r.ok).toBe(false);
		expect(r.message).toContain('Failed to fetch');
	});
});

describe('fetchLiveUsageDay', () => {
	it('这一天没有行：missing:true 是正面答案，summary 为 null', async () => {
		fetchMock.mockResolvedValue(
			response({
				ok: true,
				live: true,
				generated_at: 'x',
				source: {store: 'ok'},
				day: '2026-01-01',
				missing: true,
				summary: null,
				sessions: [],
				turns: [],
			}),
		);

		const r = await fetchLiveUsageDay('2026-01-01');

		expect(r.ok).toBe(true);
		expect(r.data?.missing).toBe(true);
		expect(r.data?.summary).toBeNull();
	});

	it('每枪一行按形状收口；缺 events 也是空数组而不是 undefined', async () => {
		fetchMock.mockResolvedValue(
			response({
				ok: true,
				live: true,
				generated_at: 'x',
				source: {},
				day: '2026-10-03',
				missing: false,
				summary: SUMMARY,
				sessions: [{session_id: 'sess_a', requests: 19}],
				turns: [
					{
						session_id: 'sess_a',
						label: '总结两个 md',
						requests: 7,
						event_count: 2,
						events: [{ts: 1, cost_cny: null, attempt: 2}, {ts: 2}],
					},
					{session_id: 'sess_a', label: '没有 events 键的一轮'},
				],
				events_truncated: 0,
			}),
		);

		const data = (await fetchLiveUsageDay('2026-10-03')).data;

		expect(data?.turns).toHaveLength(2);
		expect(data?.turns[0]?.events).toHaveLength(2);
		expect(data?.turns[0]?.events[0]?.cost_cny).toBeNull();
		expect(data?.turns[0]?.events[1]?.attempt ?? null).toBeNull();
		expect(data?.turns[1]?.events).toEqual([]);
	});

	it('后端说有行而 summary 读不出：算形状漂移，不冒充"这一天没有"', async () => {
		fetchMock.mockResolvedValue(
			response({ok: true, day: '2026-10-03', missing: false, summary: {}, turns: [], sessions: []}),
		);
		const r = await fetchLiveUsageDay('2026-10-03');
		expect(r.ok).toBe(false);
		expect(r.message).toContain('receipt_bad_live_usage_day');
	});

	it('空白日期不发请求', async () => {
		const r = await fetchLiveUsageDay('   ');
		expect(r.ok).toBe(false);
		expect(r.message).toBe('no_day');
		expect(fetchMock).not.toHaveBeenCalled();
	});
});
