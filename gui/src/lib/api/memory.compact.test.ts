/**
 * 手动 /compact 的失败原因必须能被人读懂。
 *
 * 旧实现在 !res.ok 时只给 `http_409` 这类状态码，ChatHeader 把它拼成
 * "压缩失败：http_409" —— 用户看不出是"会话正在生成"还是"会话不存在"，
 * 也就不知道下一步该做什么。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {requestManualCompact} from '@/lib/api/memory';

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

describe('requestManualCompact', () => {
	it('成功回执原样带出游标', async () => {
		fetchMock.mockResolvedValue(response({ok: true, compact_cursor: 42}));

		const r = await requestManualCompact('sess_1');

		expect(r.ok).toBe(true);
		expect(r.compact_cursor).toBe(42);
	});

	it('空会话 id 不发请求', async () => {
		const r = await requestManualCompact('   ');

		expect(r.ok).toBe(false);
		expect(r.reason).toBe('no_session');
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('409 带出后端原话，而不是 http_409', async () => {
		fetchMock.mockResolvedValue(
			response({detail: 'session is generating, compact refused'}, 409),
		);

		const r = await requestManualCompact('sess_1');

		expect(r.ok).toBe(false);
		expect(r.reason).toBe('session is generating, compact refused');
		expect(r.reason).not.toContain('http_');
	});

	it('422 的数组 detail 也能翻成一行原因', async () => {
		fetchMock.mockResolvedValue(
			response(
				{
					detail: [{loc: ['body', 'session_id'], msg: 'value is not a valid id', type: 'x'}],
				},
				422,
			),
		);

		const r = await requestManualCompact('sess_1');

		expect(r.ok).toBe(false);
		expect(r.reason).toContain('body.session_id');
	});

	it('失败回执不是 JSON 时退回状态码，不抛', async () => {
		fetchMock.mockResolvedValue({
			ok: false,
			status: 502,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		const r = await requestManualCompact('sess_1');

		expect(r.ok).toBe(false);
		expect(r.reason).toContain('502');
	});
});
