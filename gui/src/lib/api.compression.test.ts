/**
 * api.compression.test.ts — 会话压缩态回执的形状。
 *
 * 用量浮标的 C2 卡片按 `compression?.字段 ?? usage?.字段 ?? 0` 逐级回落，
 * 所以"200 但缺字段"会被渲染成"这轮还没压缩过"——一个我们没读到的事实。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fetchSessionCompression} from '@/lib/api';

const fetchMock = vi.fn();

const SNAP = {
	session_id: 'sess_1',
	c2_gate: true,
	l5_mode: 'v61',
	active: true,
	compact_cursor: 12,
	last_action: 'c2',
	turns_since_c2: 3,
	c2_summary_chars: 1840,
	c2_summary_preview: '摘要开头…',
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

describe('fetchSessionCompression', () => {
	it('9 个键齐全时原样带回', async () => {
		fetchMock.mockResolvedValue(response(SNAP));

		const r = await fetchSessionCompression('sess_1');

		expect(r.ok).toBe(true);
		expect(r.data).toEqual(SNAP);
	});

	it('403 带出后端原话（旧实现塌成 null，卡片静默回落到用量推导值）', async () => {
		fetchMock.mockResolvedValue(response({detail: 'loopback only'}, 403));

		const r = await fetchSessionCompression('sess_1');

		expect(r.ok).toBe(false);
		expect(r.data).toBeNull();
		expect(r.message).toBe('loopback only');
	});

	it.each([
		['缺 compact_cursor', {...SNAP, compact_cursor: undefined}],
		['游标不是数', {...SNAP, compact_cursor: '12'}],
		['缺 active', {...SNAP, active: undefined}],
		['turns_since_c2 是 NaN', {...SNAP, turns_since_c2: Number.NaN}],
		['缺 session_id', {...SNAP, session_id: undefined}],
	])('%s：算没读到', async (_label, payload) => {
		fetchMock.mockResolvedValue(response(payload));

		const r = await fetchSessionCompression('sess_1');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('receipt_bad_compression');
	});

	it('摘要预览缺失只清空该字段，不推翻整份快照', async () => {
		fetchMock.mockResolvedValue(response({...SNAP, c2_summary_preview: undefined}));

		const r = await fetchSessionCompression('sess_1');

		expect(r.ok).toBe(true);
		expect(r.data?.c2_summary_preview).toBe('');
		expect(r.data?.compact_cursor).toBe(12);
	});

	it('空会话 id 不发请求', async () => {
		const r = await fetchSessionCompression('   ');

		expect(r).toEqual({ok: false, data: null, message: 'no_session'});
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('连不上后端时带原因', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

		expect((await fetchSessionCompression('sess_1')).message).toContain('Failed to fetch');
	});
});
