/**
 * #14：send() 的挂起面板清理必须成对。
 *
 * 旧行为只清 pendingAsk 不清 pendingPlan：新发送后旧的计划确认框仍挂着，
 * 点它只会走 already_resolved 自愈（用户看到一个已失效的面板）。
 * 本档用「空 apiKey 早退」路径验证清理面——不触网、不依赖流。
 */
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
	it('普通发送：pendingAsk 与 pendingPlan 一并清（对偶）', async () => {
		const ok = await useChatStore.getState().sendMessage('继续');
		expect(ok).toBe(false); // 空 Key 早退（本档只验清理面）
		expect(useChatStore.getState().pendingAsk).toBeNull();
		expect(useChatStore.getState().pendingPlan).toBeNull();
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
