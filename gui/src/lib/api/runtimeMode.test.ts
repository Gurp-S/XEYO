/**
 * 审批模式写入的回执契约（权限面）。
 *
 * 旧实现是 fire-and-forget：`void fetch(...).catch(()=>{})`，按钮点一下就按新档画。
 * 后端优先级是 store 活值 > 请求 body > config 默认 ⇒ 只要本会话有过一次成功写入，
 * body 再也说不上话，这个 POST 就是改判定档的唯一通道。它失败时（403 loopback 门禁 /
 * 400 非法档 / 后端没起）引擎仍按旧档判定，UI 却报出一个没验证过的安全姿态。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {setSessionRuntimeMode} from '@/lib/api/runtimeMode';

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

describe('setSessionRuntimeMode', () => {
	it('后端回 ok 且档位对得上才算生效', async () => {
		fetchMock.mockResolvedValue(
			response({ok: true, session_id: 's1', permission_mode: 'never', effective: 'never'}),
		);

		const r = await setSessionRuntimeMode('s1', 'never');

		expect(r).toEqual({ok: true, mode: 'never', message: ''});
	});

	it('发的是 JSON body 与会话级路径', async () => {
		fetchMock.mockResolvedValue(response({ok: true, permission_mode: 'risk'}));

		await setSessionRuntimeMode('s 1', 'risk');

		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toContain('/v1/sessions/s%201/runtime-mode');
		expect(init.method).toBe('POST');
		expect(init.headers['Content-Type']).toBe('application/json');
		expect(JSON.parse(init.body)).toEqual({permission_mode: 'risk'});
	});

	it('403 带出后端原话（旧实现直接吞掉，按钮照样翻转）', async () => {
		fetchMock.mockResolvedValue(response({detail: 'loopback only'}, 403));

		const r = await setSessionRuntimeMode('s1', 'never');

		expect(r.ok).toBe(false);
		expect(r.mode).toBe('');
		expect(r.message).toBe('loopback only');
	});

	it('400 非法档：后端原话必须可见', async () => {
		fetchMock.mockResolvedValue({
			ok: false,
			status: 400,
			json: async () => ({
				detail: 'permission_mode must be one of: always / risk / never',
			}),
		});

		const r = await setSessionRuntimeMode('s1', 'yolo');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('always / risk / never');
	});

	it('回执档位与请求不一致：不算生效，并说清后端记的是哪一档', async () => {
		fetchMock.mockResolvedValue(response({ok: true, permission_mode: 'risk'}));

		const r = await setSessionRuntimeMode('s1', 'never');

		expect(r.ok).toBe(false);
		expect(r.mode).toBe('risk');
		expect(r.message).toContain('后端记的是 risk');
	});

	it('回执自报 effective 与写入档不符：也不算生效', async () => {
		fetchMock.mockResolvedValue(
			response({ok: true, permission_mode: 'never', effective: 'risk'}),
		);

		const r = await setSessionRuntimeMode('s1', 'never');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('生效值是 risk');
	});

	it('200 但回执不是对象 / 缺字段：都算未生效', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});
		expect(await setSessionRuntimeMode('s1', 'risk')).toMatchObject({
			ok: false,
			message: 'receipt_not_object',
		});

		fetchMock.mockResolvedValue(response({ok: true}));
		expect(await setSessionRuntimeMode('s1', 'risk')).toMatchObject({
			ok: false,
			message: 'receipt_missing_mode',
		});
	});

	it('ok:false 的信封不算生效', async () => {
		fetchMock.mockResolvedValue(response({ok: false, error: 'session not found'}));

		const r = await setSessionRuntimeMode('s1', 'risk');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('session not found');
	});

	it('连不上后端时 ok:false 并带原因，绝不静默', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

		const r = await setSessionRuntimeMode('s1', 'risk');

		expect(r.ok).toBe(false);
		expect(r.message).toContain('Failed to fetch');
	});

	it('空会话 id / 空档位不发请求', async () => {
		expect(await setSessionRuntimeMode('  ', 'risk')).toMatchObject({
			ok: false,
			message: 'no_session',
		});
		expect(await setSessionRuntimeMode('s1', '  ')).toMatchObject({
			ok: false,
			message: 'no_mode',
		});
		expect(fetchMock).not.toHaveBeenCalled();
	});
});
