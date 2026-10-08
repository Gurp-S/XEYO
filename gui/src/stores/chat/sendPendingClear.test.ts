/** Invalid submissions and queue receipts must preserve unresolved interactions. */
import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');

import {useChatStore} from '@/stores/chatStore';
import {useSettingsStore} from '@/stores/settingsStore';

const PLAN = {
	requestId: 'plan-1',
	plan: '计划预览',
	sessionId: 's1',
};

beforeEach(() => {
	useSettingsStore.setState({apiKey: '', provider: 'deepseek'} as never);
	useChatStore.setState({
		activeId: 's1',
		pendingAsk: {
			requestId: 'ask-1',
			question: 'q',
			options: [],
			questions: [],
			sessionId: 's1',
		},
		pendingPlan: PLAN,
	} as never);
});

describe('send() 对挂起面板的清理', () => {
	it('普通发送验证失败：pendingAsk 与 pendingPlan 均保留', async () => {
		const ok = await useChatStore.getState().sendMessage('继续');
		expect(ok).toBe(false); // 空 Key 早退（本档只验清理面）
		expect(useChatStore.getState().pendingAsk?.requestId).toBe('ask-1');
		expect(useChatStore.getState().pendingPlan).toEqual(PLAN);
	});

	it('后台跨会话发送：不碰当前会话的 pendingPlan（与 pendingAsk 同规）', async () => {
		await useChatStore
			.getState()
			.sendMessage('别的会话', undefined, [], 'agent', undefined, false, {
				background: true,
				sessionId: 's2',
			});
		expect(useChatStore.getState().pendingPlan).toEqual(PLAN);
	});
});
