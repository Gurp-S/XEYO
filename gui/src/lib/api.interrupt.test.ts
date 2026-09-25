/**
 * api.interrupt.test.ts — 停止按钮的回执。
 *
 * 旧实现是 `try { await fetch(...) } catch { /* 忽略 *\/ }`：不看 res.ok、
 * 不读回执，于是 401 / 404 / 500 / 断网一律"成功"，界面写「已停止」而后端仍在跑
 * 并继续往这条会话的 transcript 里写。后端 `POST /v1/interrupt` 返回 `{ok: bool}`，
 * 其中 false 的语义是"该会话没有可中断的回合"——那和"读不出回执"是两件事，
 * 界面对它们的说法必须不同。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {interruptChat} from '@/lib/api';

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

describe('interruptChat', () => {
	it('回执 ok=true 才算停止被确认', async () => {
		fetchMock.mockResolvedValue(response({ok: true}));

		await expect(interruptChat('s1')).resolves.toEqual({ok: true, message: ''});
	});

	it('回执 ok=false 是"没有可中断的回合"，不是失败也不是成功', async () => {
		fetchMock.mockResolvedValue(response({ok: false}));

		await expect(interruptChat('s1')).resolves.toEqual({ok: false, message: 'not_running'});
	});

	it('500 带出后端原话（旧实现把它吞成成功）', async () => {
		fetchMock.mockResolvedValue(response({detail: 'turn runner unavailable'}, 500));

		const r = await interruptChat('s1');

		expect(r.ok).toBe(false);
		expect(r.message).toBe('turn runner unavailable');
	});

	it('401 也算未确认：会话面暴露时这不是小事', async () => {
		fetchMock.mockResolvedValue(response({detail: 'unauthorized'}, 401));

		await expect(interruptChat('s1')).resolves.toMatchObject({
			ok: false,
			message: expect.stringContaining('unauthorized'),
		});
	});

	it('回执缺 ok 字段 = 读不出，不得当成成功', async () => {
		fetchMock.mockResolvedValue(response({}));

		await expect(interruptChat('s1')).resolves.toEqual({ok: false, message: 'receipt_missing_ok'});
	});

	it('ok 不是布尔值也算读不出', async () => {
		fetchMock.mockResolvedValue(response({ok: 'true'}));

		await expect(interruptChat('s1')).resolves.toEqual({ok: false, message: 'receipt_missing_ok'});
	});

	it('JSON 解析不出来时仍报未确认', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => {
				throw new Error('bad json');
			},
		});

		const r = await interruptChat('s1');

		// 解析失败在读回执这一步塌成 null，口径与"不是对象"同一条：读不出就是读不出。
		expect(r).toEqual({ok: false, message: 'receipt_not_object'});
	});

	it('断网时把原因带回来', async () => {
		fetchMock.mockRejectedValue(new Error('Failed to fetch'));

		await expect(interruptChat('s1')).resolves.toEqual({ok: false, message: 'Failed to fetch'});
	});

	it('空 session_id 不发请求', async () => {
		const r = await interruptChat('  ');

		expect(r).toEqual({ok: false, message: 'no_session'});
		expect(fetchMock).not.toHaveBeenCalled();
	});
});
