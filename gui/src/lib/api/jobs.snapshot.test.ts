/**
 * 后台任务快照读取的失败形状。
 *
 * 旧 fetchSessionJobs 在 !res.ok / 抛异常 / 回执缺 jobs 三条路上都返回
 * `{jobs: [], version: 0, wake_budget_left: 0}`，调用方按 whole-value 覆写
 * 写进 store ⇒ "没读到"被伪装成"这个会话没有在跑的任务"，而且角标轮询
 * 只在"还有任务"时继续，一次瞬时失败就永久失明（见 e9e07f2）。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fetchSessionJobs, killJob} from '@/lib/api/jobs';

const fetchMock = vi.fn();

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

describe('fetchSessionJobs', () => {
	it('200 + jobs 数组：ok:true，条目与预算原样带出', async () => {
		fetchMock.mockResolvedValue(
			response({
				jobs: [
					{
						job_id: 'bash-1',
						kind: 'bash',
						label: '回归',
						status: 'running',
						detail: '',
						reported: false,
						started_at: 1_700_000_000,
						finished_at: 0,
					},
				],
				version: 3,
				wake_budget_left: 2,
			}),
		);

		const r = await fetchSessionJobs('sess_1');

		expect(r.ok).toBe(true);
		expect(r.jobs).toHaveLength(1);
		expect(r.version).toBe(3);
		expect(r.wake_budget_left).toBe(2);
		// 后端给秒，GUI 全仓按毫秒比差值
		expect(r.jobs[0].started_at).toBe(1_700_000_000_000);
	});

	it('空任务是被证实的空（ok:true），不是读不出的兜底', async () => {
		fetchMock.mockResolvedValue(response({jobs: [], version: 7}));

		const r = await fetchSessionJobs('sess_1');

		expect(r.ok).toBe(true);
		expect(r.jobs).toEqual([]);
	});

	it('503 给出后端原话且 ok:false，调用方据此不得覆写', async () => {
		fetchMock.mockResolvedValue(response({detail: 'registry unavailable'}, 503));

		const r = await fetchSessionJobs('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('registry unavailable');
		expect(r.jobs).toEqual([]);
	});

	it('200 但回执缺 jobs 字段 = 读不出，不能画成"没有任务"', async () => {
		fetchMock.mockResolvedValue(response({version: 1}));

		const r = await fetchSessionJobs('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('jobs');
	});

	it('失败回执不是 JSON 时退回状态码，不抛', async () => {
		fetchMock.mockResolvedValue({
			ok: false,
			status: 502,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		const r = await fetchSessionJobs('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('502');
	});

	it('连不上后端时 ok:false 并带上错误信息', async () => {
		fetchMock.mockRejectedValue(new Error('Failed to fetch'));

		const r = await fetchSessionJobs('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('Failed to fetch');
	});
});

describe('killJob（F1 人侧停止）', () => {
	it('200 + ok:true 才算接受', async () => {
		fetchMock.mockResolvedValueOnce(response({ok: true, job_id: 'j1'}));
		await expect(killJob('s1', 'j1')).resolves.toBe(true);
	});

	it('200 + ok:false（已结束/未被接受）落 false，不谎报停止', async () => {
		fetchMock.mockResolvedValueOnce(response({ok: false}));
		await expect(killJob('s1', 'j1')).resolves.toBe(false);
	});

	it('404（越权/未知）与网络异常都落 false', async () => {
		fetchMock.mockResolvedValueOnce(response({message: 'job not found'}, 404));
		await expect(killJob('s1', 'j1')).resolves.toBe(false);
		fetchMock.mockRejectedValueOnce(new Error('boom'));
		await expect(killJob('s1', 'j1')).resolves.toBe(false);
	});
});
