/**
 * api.rewindGc.test.ts — 回溯清理写入的回执。
 *
 * 后端路由 docstring 自己记着这次事故：GUI 只看 `res.ok`，
 * 于是"keep_recent=0 被拒"在前端渲染成保存成功（假绿）。
 * 后端已改成 422/500，但客户端仍要认回执里的 `**saved`，
 * 并把 422 的原话带回来 —— "must be >= 1" 是可操作的，"保存失败"不是。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {setRewindGcSettings} from '@/lib/api';

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

describe('setRewindGcSettings', () => {
	it('ok 且带回落盘值时算生效', async () => {
		fetchMock.mockResolvedValue(
			response({ok: true, keep_recent: 3, max_bytes: 1024}),
		);

		const r = await setRewindGcSettings(3, 1024);

		expect(r.ok).toBe(true);
		expect(r.settings).toEqual({keep_recent: 3, max_bytes: 1024});
	});

	it('null 是合法的"该项未设置"', async () => {
		fetchMock.mockResolvedValue(response({ok: true, keep_recent: null, max_bytes: null}));

		const r = await setRewindGcSettings(null, null);

		expect(r.ok).toBe(true);
		expect(r.settings).toEqual({keep_recent: null, max_bytes: null});
	});

	it('422 带出后端原话（旧实现只剩一个 false，界面只能说"保存失败"）', async () => {
		fetchMock.mockResolvedValue(response({detail: 'keep_recent must be >= 1'}, 422));

		const r = await setRewindGcSettings(0, null);

		expect(r.ok).toBe(false);
		expect(r.settings).toBeNull();
		expect(r.message).toBe('keep_recent must be >= 1');
	});

	it('500（写盘失败）带出原因', async () => {
		fetchMock.mockResolvedValue(response({detail: 'Read-only file system'}, 500));

		expect((await setRewindGcSettings(1, null)).message).toContain('Read-only');
	});

	it('200 但 ok 不为 true / 缺字段 / 值不是数：都不算生效', async () => {
		fetchMock.mockResolvedValue(response({ok: false}));
		expect((await setRewindGcSettings(1, 1)).ok).toBe(false);

		fetchMock.mockResolvedValue(response({ok: true}));
		expect(await setRewindGcSettings(1, 1)).toMatchObject({
			ok: false,
			message: 'receipt_missing_fields',
		});

		fetchMock.mockResolvedValue(response({ok: true, keep_recent: '3', max_bytes: null}));
		expect((await setRewindGcSettings(3, null)).ok).toBe(false);
	});

	it('连不上后端时带原因，不静默', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

		expect((await setRewindGcSettings(1, null)).message).toContain('Failed to fetch');
	});

	it('发的是 PUT 与两个可空字段', async () => {
		fetchMock.mockResolvedValue(response({ok: true, keep_recent: 2, max_bytes: null}));

		await setRewindGcSettings(2, null);

		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toContain('/v1/settings/rewind-gc');
		expect(init.method).toBe('PUT');
		expect(JSON.parse(init.body)).toEqual({keep_recent: 2, max_bytes: null});
	});
});
