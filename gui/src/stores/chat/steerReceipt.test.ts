/**
 * steerReceipt.test.ts — 边界投递回执撤卡的纯函数守卫。
 *
 * 事故原型：引导（steer）的 202 被当成"已排队"处理，塞进一张 queue_id 为空的
 * 排队卡 ⇒ DELETE /inbox/ 空 id 必 400，卡片删不掉，只能等下次 refreshInbox 覆盖。
 */
import {describe, expect, it} from 'vitest';
import {dropDeliveredInboxChips} from './preStoreHelpers';
import type {InboxQueuedItem} from './preStoreHelpers';

const chip = (over: Partial<InboxQueuedItem>): InboxQueuedItem => ({
	queue_id: 'q1',
	text: 't',
	media_refs: [],
	message_id: null,
	queued_at: 0,
	attempts: 0,
	state: 'queued',
	position: 0,
	...over,
});

describe('dropDeliveredInboxChips', () => {
	const inbox = {
		s1: [chip({queue_id: 'a', message_id: 'm-1'}), chip({queue_id: 'b', message_id: 'm-2'})],
	};

	it('按消息号撤掉已投递的卡，留下别的', () => {
		const out = dropDeliveredInboxChips(inbox, 's1', ['m-1']);
		expect(out.s1.map(i => i.queue_id)).toEqual(['b']);
	});

	it('无匹配 / 空回执 / 未知会话都返回原对象（不制造新引用）', () => {
		expect(dropDeliveredInboxChips(inbox, 's1', [])).toBe(inbox);
		expect(dropDeliveredInboxChips(inbox, 's1', ['nope'])).toBe(inbox);
		expect(dropDeliveredInboxChips(inbox, 'other', ['m-1'])).toBe(inbox);
	});

	it('没有消息号的卡不会被误撤（只能靠 queue_id 管理）', () => {
		const withNull = {s1: [chip({queue_id: 'a', message_id: null})]};
		expect(dropDeliveredInboxChips(withNull, 's1', [''])).toBe(withNull);
		expect(dropDeliveredInboxChips(withNull, 's1', ['m-1']).s1).toHaveLength(1);
	});
});
