/**
 * sessionTaskReceipt.test.ts — 任务快照读不出时不得结算回合。
 *
 * /v1/sessions/{id}/task 是"这一轮还在不在跑"的唯一读侧依据：
 * streamRecoverySlice 拿它决定重连还是 finalizeFinishedTurn。
 * 缺字段的 200 过去是一个"读得到内容"的快照，busy / status 都是 undefined
 * ⇒ running=false ⇒ 把仍在跑的回合显示成已结束。
 * 现在形状不对就走函数已有的 catch ⇒ 返回 null，
 * 而 null 的含义（读不到，退避后重试）才是诚实的。
 * 形体取自 python/server/routers/sessions.py::session_task 的三个分支。
 */
import {describe, expect, it, vi} from 'vitest';
import {fetchSessionTask, parseSessionTask} from '@/lib/api';

const running = {
	ok: true,
	status: 'running',
	session_id: 's1',
	turn_id: 't1',
	last_event_id: 12,
	stop_reason: '',
	goal_text: '把这一轮跑完',
	waiting_permission: false,
	revision: 3,
	model: 'deepseek-chat',
	busy: true,
};

const idle = {
	ok: true,
	status: 'idle',
	session_id: 's1',
	turn_id: '',
	last_event_id: 0,
	stop_reason: '',
	goal_text: '',
	waiting_permission: false,
	busy: false,
};

function stubJson(payload: unknown) {
	return vi.fn().mockResolvedValue({ok: true, status: 200, json: async () => payload});
}

describe('任务快照回执', () => {
	it('running 与 idle 两种自洽形状都通过', () => {
		expect(parseSessionTask(running)).toMatchObject({status: 'running', busy: true});
		expect(parseSessionTask(idle)).toMatchObject({status: 'idle', busy: false});
	});

	it('缺 busy / status 不得变成一个"没在跑"的快照', () => {
		expect(() => parseSessionTask({...running, busy: undefined})).toThrow(/status \/ busy/);
		expect(() => parseSessionTask({...running, status: undefined})).toThrow(/status \/ busy/);
	});

	it('busy / waiting_permission 必须是布尔，last_event_id 必须是数字', () => {
		expect(() => parseSessionTask({...running, busy: 'true'})).toThrow(/status \/ busy/);
		expect(() => parseSessionTask({...running, waiting_permission: null})).toThrow(/status \/ busy/);
		expect(() => parseSessionTask({...running, last_event_id: '12'})).toThrow(/status \/ busy/);
	});

	it('replay 游标与可选字段（revision / model）互不牵连', () => {
		expect(parseSessionTask({...running, revision: undefined, model: undefined})).toMatchObject({
			last_event_id: 12,
		});
	});
});

describe('客户端确实走了解析', () => {
	it('200 + 缺 busy ⇒ 返回 null（读不到），不是一个可结算的快照', async () => {
		vi.stubGlobal('fetch', stubJson({...running, busy: undefined}));
		await expect(fetchSessionTask('s1')).resolves.toBeNull();
		vi.unstubAllGlobals();
	});

	it('200 + 完整快照 ⇒ 原样交给重连逻辑', async () => {
		vi.stubGlobal('fetch', stubJson(running));
		await expect(fetchSessionTask('s1')).resolves.toMatchObject({status: 'running', busy: true});
		vi.unstubAllGlobals();
	});

	it('非 200 仍按既有约定返回 null', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: false, status: 404, json: async () => ({detail: 'no such session'})}));
		await expect(fetchSessionTask('missing')).resolves.toBeNull();
		vi.unstubAllGlobals();
	});
});
