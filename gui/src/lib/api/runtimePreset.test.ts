/**
 * 会话权限 preset 写入必须是可 await 的回执。
 *
 * 旧实现是 fire-and-forget（`void fetch(...).catch(()=>{})`），
 * RuntimePresetSetting 点一下就本地标"已生效"：403（loopback 门禁）/
 * 422（非法会话 id）时引擎其实还按旧 preset 判定，UI 却报出一个假的安全姿态。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
	fetchSessionRuntimePreset,
	setSessionRuntimePreset,
} from '@/lib/api/runtimePreset';

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

describe('setSessionRuntimePreset', () => {
	it('后端接受才算 ok', async () => {
		fetchMock.mockResolvedValue(response({ok: true, permission_preset: 'full'}));

		const r = await setSessionRuntimePreset('sess_1', 'full');

		expect(r.ok).toBe(true);
		expect(r.message).toBe('');
	});

	it('403 带出后端原话（旧实现直接吞掉）', async () => {
		fetchMock.mockResolvedValue(response({detail: 'loopback only'}, 403));

		const r = await setSessionRuntimePreset('sess_1', 'full');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('loopback only');
	});

	it('200 但 ok:false 也算未生效', async () => {
		fetchMock.mockResolvedValue(response({ok: false, error: 'session not found'}));

		const r = await setSessionRuntimePreset('sess_1', 'full');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('session not found');
	});

	it('空会话 id 不发请求', async () => {
		const r = await setSessionRuntimePreset('  ', 'full');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('no_session');
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('失败回执不是 JSON 时退回状态码，不抛', async () => {
		fetchMock.mockResolvedValue({
			ok: false,
			status: 500,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		const r = await setSessionRuntimePreset('sess_1', 'full');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('500');
	});

	it('连不上后端时 ok:false，绝不静默', async () => {
		fetchMock.mockRejectedValue(new Error('Failed to fetch'));

		const r = await setSessionRuntimePreset('sess_1', 'full');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('Failed to fetch');
	});
});

/**
 * 读侧的要害是三种状态必须可分：
 * "确认未切换"（后端认账）、"读到了某一档"、"根本没读到"。
 * 旧实现把后两种都塌成 `null`，于是 403 / 后端没起 时面板画成
 * "没有任何选中项 + 沿用创建时钉死的 preset"——一个自己没验证过的安全姿态。
 */
describe('fetchSessionRuntimePreset', () => {
	it('permission_preset 为 null 是"确认未显式切换"，不是失败', async () => {
		fetchMock.mockResolvedValue(
			response({ok: true, session_id: 'sess_1', permission_preset: null}),
		);

		const r = await fetchSessionRuntimePreset('sess_1');

		expect(r).toEqual({ok: true, preset: null, message: ''});
	});

	it('正常活值原样带回（去空白）', async () => {
		fetchMock.mockResolvedValue(
			response({ok: true, session_id: 'sess_1', permission_preset: ' workspace-write '}),
		);

		const r = await fetchSessionRuntimePreset('sess_1');

		expect(r.ok).toBe(true);
		expect(r.preset).toBe('workspace-write');
	});

	it('403 时 ok:false 并带出后端原话（旧实现塌成 null，与"未切换"同形）', async () => {
		fetchMock.mockResolvedValue(response({detail: 'loopback only'}, 403));

		const r = await fetchSessionRuntimePreset('sess_1');

		expect(r.ok).toBe(false);
		expect(r.preset).toBeNull();
		expect(r.message).toBe('loopback only');
	});

	it('200 但回执不是对象：失败而不是"未切换"', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		const r = await fetchSessionRuntimePreset('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('receipt_not_object');
	});

	it('200 但缺 permission_preset 字段：字段缺失不等于该档没有值', async () => {
		fetchMock.mockResolvedValue(response({ok: true, session_id: 'sess_1'}));

		const r = await fetchSessionRuntimePreset('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('receipt_missing_preset');
	});

	it('200 但字段是空串/非法类型：不当成有效档', async () => {
		fetchMock.mockResolvedValue(
			response({ok: true, session_id: 'sess_1', permission_preset: '   '}),
		);
		expect((await fetchSessionRuntimePreset('sess_1')).ok).toBe(false);

		fetchMock.mockResolvedValue(
			response({ok: true, session_id: 'sess_1', permission_preset: 7}),
		);
		expect((await fetchSessionRuntimePreset('sess_1')).ok).toBe(false);
	});

	it('ok:false 的回执不算读到', async () => {
		fetchMock.mockResolvedValue(response({ok: false, error: 'session not found'}));

		const r = await fetchSessionRuntimePreset('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('session not found');
	});

	it('连不上后端时 ok:false 并带原因', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

		const r = await fetchSessionRuntimePreset('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('Failed to fetch');
	});

	it('空会话 id 不发请求', async () => {
		const r = await fetchSessionRuntimePreset('  ');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('no_session');
		expect(fetchMock).not.toHaveBeenCalled();
	});
});
