/**
 * permissions.resolve.test.ts — 三个裁决客户端的回执形状。
 *
 * 旧实现返回 boolean 且 `catch { return false }`：
 * "服务端说这项已经被别处答过"、"422 拒收这个 outcome"、"根本没送达"
 * 三件事在界面上是同一句「提交失败，请重试」——前两句重试都无意义，
 * 第一句甚至根本不是失败（裁决已经生效）。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {resolveAsk, resolveFailureText, resolvePermission, resolvePlan} from '@/lib/api';

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

describe('resolvePermission', () => {
	it('ok=true 才算生效，且不带回失败原因', async () => {
		fetchMock.mockResolvedValue(response({ok: true, request_id: 'a1', grant_id: ''}));
		await expect(resolvePermission('a1', true)).resolves.toEqual({
			ok: true,
			reason: '',
			message: '',
		});
	});

	it('后端说"已被别处答复"时把 reason 带回来', async () => {
		fetchMock.mockResolvedValue(
			response({ok: false, request_id: 'a1', grant_id: '', reason: 'already_resolved'}),
		);
		await expect(resolvePermission('a1', true)).resolves.toMatchObject({
			ok: false,
			reason: 'already_resolved',
		});
	});

	it('422 带出后端原话，而不是笼统的失败', async () => {
		fetchMock.mockResolvedValue(response({detail: 'outcome must be allow / deny / remind'}, 422));
		// 强转：这一档就是"客户端类型之外、真实可能发出去的错误 body"，
		// 后端 422 的原话必须能一路带回界面（见 control.py 里 outcome 的事故注释）。
		const r = await resolvePermission('a1', true, 'desktop', 'deny-all' as 'allow');
		expect(r.ok).toBe(false);
		expect(r.reason).toBe('http');
		expect(r.message).toBe('outcome must be allow / deny / remind');
	});

	it('回执缺 ok 字段 = 读不出，不得当成生效', async () => {
		fetchMock.mockResolvedValue(response({request_id: 'a1'}));
		await expect(resolvePermission('a1', false)).resolves.toMatchObject({
			ok: false,
			reason: 'receipt_missing_ok',
			message: '回执缺少 ok 字段',
		});
	});

	it('断网时 reason=network，界面才知道该说的是"未送达"', async () => {
		fetchMock.mockRejectedValue(new Error('Failed to fetch'));
		await expect(resolvePermission('a1', true)).resolves.toMatchObject({
			ok: false,
			reason: 'network',
			message: 'Failed to fetch',
		});
	});
});

describe('resolveAsk / resolvePlan 同一形状', () => {
	it('ask 生效与不生效都读得出来', async () => {
		fetchMock.mockResolvedValue(response({ok: true, request_id: 'q1'}));
		await expect(resolveAsk('q1', 'a')).resolves.toEqual({ok: true, reason: '', message: ''});

		fetchMock.mockResolvedValue(response({ok: false, request_id: 'q1', reason: 'no_such_request'}));
		await expect(resolveAsk('q1', 'a')).resolves.toMatchObject({
			ok: false,
			reason: 'no_such_request',
		});
	});

	it('plan 走同一个回执（它此前连失败都不看）', async () => {
		fetchMock.mockResolvedValue(response({ok: true}));
		await expect(resolvePlan('p1', true)).resolves.toEqual({ok: true, reason: '', message: ''});

		fetchMock.mockResolvedValue(response({ok: false, reason: 'already_resolved'}));
		await expect(resolvePlan('p1', false)).resolves.toMatchObject({
			ok: false,
			reason: 'already_resolved',
		});
	});
});

describe('resolveFailureText 的三分法', () => {
	it('已被别处答复不是失败', () => {
		const n = resolveFailureText({ok: false, reason: 'already_resolved', message: 'x'});
		expect(n.tone).toBe('info');
		expect(n.text).toContain('已在别处答复');
	});

	it('挂起项不在服务端时不让人白重试', () => {
		const n = resolveFailureText({ok: false, reason: 'no_such_request', message: 'x'});
		expect(n.tone).toBe('error');
		expect(n.text).toContain('服务可能重启过');
		expect(n.text).not.toContain('请重试');
	});

	it('其余情况把后端原话带出来', () => {
		const n = resolveFailureText({ok: false, reason: 'http', message: 'outcome must be allow / deny / remind'});
		expect(n.text).toContain('outcome must be allow / deny / remind');
	});
});
