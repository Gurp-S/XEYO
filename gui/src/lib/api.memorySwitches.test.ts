/**
 * api.memorySwitches.test.ts — 记忆开关注册表读写的回执形状。
 *
 * 后端两处约定必须照住：拒绝未知键时回的是 **200 + {ok:false, error}**（不是 4xx），
 * 而面板旧代码只读 `message` ⇒ 那句"未知记忆开关: XEYO_…"被丢成一句泛化失败。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {getMemorySwitches, setMemorySwitches} from '@/lib/api';

const fetchMock = vi.fn();

const SW = {
	XEYO_L5: {
		key: 'XEYO_L5',
		label: 'L5 模式',
		value: 'v61',
		allowed: ['project', 'v61'],
		source: 'settings',
		default: 'project',
		exposed: true,
		effective: 'v61',
	},
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

describe('getMemorySwitches', () => {
	it('ok + switches 齐全时带回整份数据', async () => {
		fetchMock.mockResolvedValue(response({ok: true, switches: SW, stale: ['XEYO_OLD']}));

		const r = await getMemorySwitches();

		expect(r.ok).toBe(true);
		expect(r.data?.switches).toEqual(SW);
		expect(r.data?.stale).toEqual(['XEYO_OLD']);
	});

	it('403 带出后端原话（旧实现塌成 null，面板画成"没有可切换的开关"）', async () => {
		fetchMock.mockResolvedValue(response({detail: 'loopback only'}, 403));

		const r = await getMemorySwitches();

		expect(r.ok).toBe(false);
		expect(r.data).toBeNull();
		expect(r.message).toBe('loopback only');
	});

	it('200 但缺 switches：算没读到，不让空表冒充"没有开关"', async () => {
		fetchMock.mockResolvedValue(response({ok: true}));

		const r = await getMemorySwitches();

		expect(r.ok).toBe(false);
		expect(r.message).toBe('receipt_missing_switches');
	});

	it('200 但 switches 是数组：同样算没读到', async () => {
		fetchMock.mockResolvedValue(response({ok: true, switches: []}));

		expect((await getMemorySwitches()).ok).toBe(false);
	});

	it('连不上后端时带原因', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

		expect((await getMemorySwitches()).message).toContain('Failed to fetch');
	});
});

describe('setMemorySwitches', () => {
	it('后端按 200 拒绝未知键时，error 原话必须带回来', async () => {
		fetchMock.mockResolvedValue(
			response({ok: false, error: '未知记忆开关: XEYO_NOPE'}),
		);

		const r = await setMemorySwitches({XEYO_NOPE: '1'});

		expect(r.ok).toBe(false);
		expect(r.message).toBe('未知记忆开关: XEYO_NOPE');
	});

	it('写成功时带回新表（含 pruned 回执）', async () => {
		fetchMock.mockResolvedValue(response({ok: true, switches: SW, pruned: ['XEYO_OLD']}));

		const r = await setMemorySwitches({});

		expect(r.ok).toBe(true);
		expect(r.data?.pruned).toEqual(['XEYO_OLD']);
	});

	it('POST 形状：updates 包一层、带鉴权头', async () => {
		fetchMock.mockResolvedValue(response({ok: true, switches: SW}));

		await setMemorySwitches({XEYO_L5: 'project'});

		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toContain('/v1/settings/memory');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({updates: {XEYO_L5: 'project'}});
	});
});
