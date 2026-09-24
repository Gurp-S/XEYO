/**
 * 授权台账读取的失败形状（安全面）。
 *
 * 旧实现 `!res.ok → []`、异常 `→ []`、回执缺 grants `→ []`，三条路都返回"空列表"，
 * 于是面板画成"暂无授权"——把"读不出"伪装成"确实没有"。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {listPermissionGrants} from '@/lib/api/permissions';

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

describe('listPermissionGrants', () => {
	it('正常回执：ok:true + 条目原样带出', async () => {
		fetchMock.mockResolvedValue(
			response({grants: [{grant_id: 'a1b2c3d4e5f6', tool_name: 'Bash'}]}),
		);

		const r = await listPermissionGrants();

		expect(r.ok).toBe(true);
		expect(r.grants).toHaveLength(1);
		expect(r.message).toBe('');
	});

	it('确实没有授权才是 ok:true + 空列表', async () => {
		fetchMock.mockResolvedValue(response({grants: []}));

		const r = await listPermissionGrants();

		expect(r.ok).toBe(true);
		expect(r.grants).toEqual([]);
	});

	it('401/422 不是空列表，而是带原因的读取失败', async () => {
		fetchMock.mockResolvedValue(response({detail: 'invalid or missing token'}, 401));

		const r = await listPermissionGrants();

		expect(r.ok).toBe(false);
		expect(r.grants).toEqual([]);
		expect(r.message).toBe('invalid or missing token');
	});

	it('回执缺 grants 字段 = 读不出，不能当"没有授权"', async () => {
		fetchMock.mockResolvedValue(response({}));

		const r = await listPermissionGrants();

		expect(r.ok).toBe(false);
		expect(r.message).toContain('grants');
	});

	it('grants 不是数组时同样按读不出处理', async () => {
		fetchMock.mockResolvedValue(response({grants: {a: 1}}));

		const r = await listPermissionGrants();

		expect(r.ok).toBe(false);
		expect(r.message).toContain('grants');
	});

	it('连不上后端时 ok:false，且不抛给调用方', async () => {
		fetchMock.mockRejectedValue(new Error('Failed to fetch'));

		const r = await listPermissionGrants();

		expect(r.ok).toBe(false);
		expect(r.message).toBeTruthy();
	});
});
