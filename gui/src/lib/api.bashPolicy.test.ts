/**
 * api.bashPolicy.test.ts — 工作区 Bash 策略读写的回执形状。
 *
 * 后端固定回 {ok, cwd, bash_routing, bash_escalate, escalate_recommended, escalate_max, escalate_min}。
 * 旧客户端 200 直接 `as BashPolicy` 返回，少回任何一个键界面照样按客户端编的默认值
 * 显示"推荐 3 / 上限 5"——那两个数字是策略事实，不是 UI 的猜测。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {loadBashPolicy, saveBashPolicy} from '@/lib/api';

const fetchMock = vi.fn();

const POLICY = {
	ok: true,
	cwd: 'D:/proj',
	bash_routing: 'auto',
	bash_escalate: 3,
	escalate_recommended: 3,
	escalate_max: 5,
	escalate_min: 0,
};

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

describe('loadBashPolicy', () => {
	it('形状齐全时原样带回策略', async () => {
		fetchMock.mockResolvedValue(response(POLICY));

		const r = await loadBashPolicy('D:/proj');

		expect(r.ok).toBe(true);
		expect(r.policy).toEqual(POLICY);
		expect(r.message).toBe('');
	});

	it('403 带出后端原话（旧实现只回 null，界面写"读取失败"）', async () => {
		fetchMock.mockResolvedValue(response({detail: 'loopback only'}, 403));

		const r = await loadBashPolicy('D:/proj');

		expect(r.ok).toBe(false);
		expect(r.policy).toBeNull();
		expect(r.message).toBe('loopback only');
	});

	it.each([
		['缺 escalate_max', {...POLICY, escalate_max: undefined}],
		['routing 是别的档', {...POLICY, bash_routing: 'sometimes'}],
		['escalate 不是数', {...POLICY, bash_escalate: '3'}],
		['escalate 是负数', {...POLICY, bash_escalate: -1}],
		['ok 不为 true', {...POLICY, ok: false}],
	])('%s：算没读到，不让客户端默认值冒充策略', async (_label, payload) => {
		fetchMock.mockResolvedValue(response(payload));

		const r = await loadBashPolicy('D:/proj');

		expect(r.ok).toBe(false);
		expect(r.policy).toBeNull();
		expect(r.message).toBe('receipt_bad_policy');
	});

	it('200 但不是 JSON：不崩在解析上，回可读原因', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		const r = await loadBashPolicy('D:/proj');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('receipt_bad_policy');
	});

	it('连不上后端时带原因', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

		const r = await loadBashPolicy('D:/proj');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('Failed to fetch');
	});
});

describe('saveBashPolicy', () => {
	it('发的是 POST + 三项 body', async () => {
		fetchMock.mockResolvedValue(response(POLICY));

		await saveBashPolicy({bash_routing: 'auto', bash_escalate: 3, workspace: 'D:/proj'});

		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toContain('/v1/workspace/policy-bash');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({
			bash_routing: 'auto',
			bash_escalate: 3,
			workspace: 'D:/proj',
		});
	});

	it('400（超上限被后端拒）时带出原话，不返回 null 让界面猜', async () => {
		fetchMock.mockResolvedValue(
			response({detail: 'bash_escalate must be <= 5'}, 400),
		);

		const r = await saveBashPolicy({bash_escalate: 9});

		expect(r.ok).toBe(false);
		expect(r.message).toContain('must be <= 5');
	});

	it('200 但形状不对：不算保存成功', async () => {
		fetchMock.mockResolvedValue(response({ok: true}));

		const r = await saveBashPolicy({bash_escalate: 2});

		expect(r.ok).toBe(false);
		expect(r.policy).toBeNull();
	});
});
