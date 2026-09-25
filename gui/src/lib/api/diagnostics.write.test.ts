/**
 * diagnostics.write.test.ts — 固定证据与验收记录这几个客户端的回执形状。
 *
 * 钉两件事：
 * 1. 200 信封里的 `{ok:false}` 不是成功（诊断/实验端点大量用 200 回拒绝）；
 * 2. 读不出时不得塌成"没有 pin / 已删除"——那是把观测失败说成运行事实。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {deleteDiagPin, fetchDiagPins, recordDiagVerifier} from '@/lib/api/diagnostics';

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

describe('deleteDiagPin', () => {
	it('200 + ok:true 才算删掉', async () => {
		fetchMock.mockResolvedValue(response({ok: true}));
		await expect(deleteDiagPin('pin_1', 's1')).resolves.toEqual({ok: true, error: ''});
	});

	it('200 + ok:false 带着后端原话，不得读成已删除', async () => {
		fetchMock.mockResolvedValue(response({ok: false, error: 'no such pin'}));
		await expect(deleteDiagPin('pin_x', 's1')).resolves.toEqual({
			ok: false,
			error: 'no such pin',
		});
	});

	it('200 但信封里没有 ok 字段 = 读不出', async () => {
		fetchMock.mockResolvedValue(response({}));
		const r = await deleteDiagPin('pin_1', 's1');
		expect(r.ok).toBe(false);
		expect(r.error).toContain('HTTP 200');
	});

	it('422 带出校验原话', async () => {
		fetchMock.mockResolvedValue(response({detail: 'pin_id 含非法字符'}, 422));
		const r = await deleteDiagPin('../etc/passwd', 's1');
		expect(r.ok).toBe(false);
		expect(r.error).toContain('pin_id');
	});
});

describe('recordDiagVerifier', () => {
	it('200 + ok:true 时把 pin 读回来', async () => {
		fetchMock.mockResolvedValue(
			response({ok: true, pin: {pin_id: 'v1', kind: 'verifier', name: 'pytest', exit_code: 1}}),
		);
		const r = await recordDiagVerifier('s1', 't1', {name: 'pytest', exit_code: 1});
		expect(r.ok).toBe(true);
		expect(r.pin?.pin_id).toBe('v1');
		expect(r.pin?.exit_code).toBe(1);
	});

	it('200 + ok:false 不是"已记录验收"', async () => {
		fetchMock.mockResolvedValue(response({ok: false, error: 'unknown turn'}));
		const r = await recordDiagVerifier('s1', 't404', {name: 'pytest'});
		expect(r.ok).toBe(false);
		expect(r.pin).toBeNull();
		expect(r.error).toBe('unknown turn');
	});

	it('省略 exit_code 时不补 0：未运行与运行成功是两件事', async () => {
		fetchMock.mockResolvedValue(response({ok: true, pin: {pin_id: 'v2', kind: 'verifier'}}));
		await recordDiagVerifier('s1', 't1', {name: 'pytest'});
		const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
		expect('exit_code' in body).toBe(false);
	});

	it('HTTP 失败抛的是带后端原话的错误，不静默返回 ok:false', async () => {
		fetchMock.mockResolvedValue(response({detail: 'body too large'}, 413));
		await expect(recordDiagVerifier('s1', 't1', {name: 'pytest'})).rejects.toThrow(/body too large/);
	});
});

describe('fetchDiagPins', () => {
	it('正常列出固定记录', async () => {
		fetchMock.mockResolvedValue(
			response({pins: [{pin_id: 'p1', kind: 'run_mark'}, {pin_id: 'p2', kind: 'verifier'}]}),
		);
		const pins = await fetchDiagPins('s1', 't1');
		expect(pins.map(p => p.pin_id)).toEqual(['p1', 'p2']);
	});

	it('后端 200 但缺 pins 字段时得到空表（形状问题），HTTP 失败则抛错而非空表', async () => {
		fetchMock.mockResolvedValue(response({}));
		expect(await fetchDiagPins('s1')).toEqual([]);

		fetchMock.mockResolvedValue(response({detail: 'boom'}, 500));
		await expect(fetchDiagPins('s1')).rejects.toThrow(/boom/);
	});
});
