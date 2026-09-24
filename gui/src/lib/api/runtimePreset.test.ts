/**
 * 会话权限 preset 写入必须是可 await 的回执。
 *
 * 旧实现是 fire-and-forget（`void fetch(...).catch(()=>{})`），
 * RuntimePresetSetting 点一下就本地标"已生效"：403（loopback 门禁）/
 * 422（非法会话 id）时引擎其实还按旧 preset 判定，UI 却报出一个假的安全姿态。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {setSessionRuntimePreset} from '@/lib/api/runtimePreset';

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
