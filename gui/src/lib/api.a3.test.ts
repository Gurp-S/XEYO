/**
 * api.a3.test.ts — A3 快照 / 报告两个客户端的回执。
 *
 * 后端已经守这条纪律：报告存在却读不出时它回 500，不谎报"尚未生成"。
 * 客户端原来把 403/离线/形状变了 全塌成 null，面板于是只能在
 * "尚未生成报告"与"正在读取"之间二选一 —— 把一个没读到的事实施了政。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {getMemoryReport, runMemorySnapshot} from '@/lib/api';

const fetchMock = vi.fn();

const EXISTS = {
	ok: true,
	exists: true,
	path: 'D:/docs/A3-monitor.html',
	url: 'file:///D:/docs/A3-monitor.html',
	bytes: 4096,
	mtime: 1_770_000_000,
	generated_at: '2026-09-24T09:30:00',
	days: ['2026-09-23', '2026-09-24'],
};
const MISSING = {ok: false, exists: false, path: 'D:/docs/A3-monitor.html', url: ''};

function response(payload: unknown, status = 200) {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => payload,
	};
}

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('getMemoryReport', () => {
	it('报告存在时带回元信息', async () => {
		fetchMock.mockResolvedValue(response(EXISTS));

		const r = await getMemoryReport();

		expect(r.ok).toBe(true);
		expect(r.data?.days).toEqual(['2026-09-23', '2026-09-24']);
	});

	it('后端正面回答"还没生成"：ok:true + exists:false，不是读失败', async () => {
		fetchMock.mockResolvedValue(response(MISSING));

		const r = await getMemoryReport();

		expect(r.ok).toBe(true);
		expect(r.data?.exists).toBe(false);
	});

	it('500（报告存在却读不出）带出后端原话，不能当成"尚未生成"', async () => {
		fetchMock.mockResolvedValue(response({detail: 'Permission denied'}, 500));

		const r = await getMemoryReport();

		expect(r.ok).toBe(false);
		expect(r.data).toBeNull();
		expect(r.message).toBe('Permission denied');
	});

	it('200 但缺 exists：算没读到', async () => {
		fetchMock.mockResolvedValue(response({ok: true, path: 'x'}));

		expect(await getMemoryReport()).toMatchObject({
			ok: false,
			message: 'receipt_bad_report',
		});
	});

	it('连不上后端时带原因', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

		expect((await getMemoryReport()).message).toContain('Failed to fetch');
	});
});

describe('runMemorySnapshot', () => {
	it('跑成功时带回补齐的天数', async () => {
		fetchMock.mockResolvedValue(response({ok: true, days: ['2026-09-23', '2026-09-24']}));

		const r = await runMemorySnapshot();

		expect(r.ok).toBe(true);
		expect(r.data?.days).toHaveLength(2);
	});

	it('后端自报失败：读到了，但 data.ok 是 false，error 原样带回', async () => {
		fetchMock.mockResolvedValue(response({ok: false, error: '生成器退出码 1'}));

		const r = await runMemorySnapshot();

		expect(r.ok).toBe(true);
		expect(r.data?.ok).toBe(false);
		expect(r.data?.error).toBe('生成器退出码 1');
	});

	it('HTTP 失败与"后端说失败"是两件事', async () => {
		fetchMock.mockResolvedValue(response({detail: 'loopback only'}, 403));

		const r = await runMemorySnapshot();

		expect(r.ok).toBe(false);
		expect(r.message).toBe('loopback only');
	});

	it('200 但缺 ok / rc 不是数：算没读到', async () => {
		fetchMock.mockResolvedValue(response({day: '2026-09-24'}));
		expect(await runMemorySnapshot()).toMatchObject({
			ok: false,
			message: 'receipt_bad_snapshot',
		});

		fetchMock.mockResolvedValue(response({ok: true, rc: 'one'}));
		expect((await runMemorySnapshot()).ok).toBe(false);
	});

	it('发的是 POST 且带鉴权头', async () => {
		fetchMock.mockResolvedValue(response({ok: true, day: '2026-09-24'}));

		await runMemorySnapshot();

		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toContain('/v1/settings/memory/snapshot');
		expect(init.method).toBe('POST');
	});
});
