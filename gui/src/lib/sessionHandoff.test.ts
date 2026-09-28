import {beforeEach, describe, expect, it, vi} from 'vitest';
import {SIDE_SPACE_ID} from '@/lib/db';
import type {ChatSession} from '@/lib/types';
import {useChatStore} from '@/stores/chatStore';
import {handoffHiddenActiveSession, pickHandoffSessionId} from './sessionHandoff';

/**
 * 页面视图背后当前会话消失后的交接规则（bug #2 / #3 的判定核心）。
 * 调用点回归在 components/Sidebar.test.tsx。
 */

function sess(
	id: string,
	spaceId: string,
	partial?: Partial<ChatSession>,
): ChatSession {
	return {
		id,
		spaceId,
		title: id,
		createdAt: 0,
		updatedAt: 0,
		...partial,
	};
}

const realSelectSession = useChatStore.getState().selectSession;

beforeEach(() => {
	useChatStore.setState({
		sessions: [],
		activeId: null,
		selectSession: realSelectSession,
	});
	vi.restoreAllMocks();
});

describe('pickHandoffSessionId', () => {
	it('主会话优先接班同工作区的未归档会话', () => {
		const list = [
			sess('b1', 'B'),
			sess('a1', 'A'),
			sess('a2', 'A'),
			sess('s1', SIDE_SPACE_ID),
		];
		expect(pickHandoffSessionId(list, {id: 'a1', spaceId: 'A'})).toBe('a2');
	});

	it('同区没有活口时取任意主会话，绝不取侧聊', () => {
		const list = [sess('s1', SIDE_SPACE_ID), sess('b1', 'B'), sess('a1', 'A')];
		expect(pickHandoffSessionId(list, {id: 'a1', spaceId: 'A'})).toBe('b1');
	});

	it('只剩已归档与侧聊时返回 null（刻意回新对话态）', () => {
		const list = [
			sess('s1', SIDE_SPACE_ID),
			sess('b2', 'B', {archived: true}),
			sess('a1', 'A'),
		];
		expect(pickHandoffSessionId(list, {id: 'a1', spaceId: 'A'})).toBeNull();
	});

	it('侧聊只交给另一条侧聊', () => {
		const list = [sess('b1', 'B'), sess('s1', SIDE_SPACE_ID), sess('s2', SIDE_SPACE_ID)];
		expect(
			pickHandoffSessionId(list, {id: 's1', spaceId: SIDE_SPACE_ID}),
		).toBe('s2');
		const onlyMain = [sess('b1', 'B'), sess('s1', SIDE_SPACE_ID)];
		expect(
			pickHandoffSessionId(onlyMain, {id: 's1', spaceId: SIDE_SPACE_ID}),
		).toBeNull();
	});
});

describe('handoffHiddenActiveSession', () => {
	it('await 到 selectSession 真的落地才算交接完成', async () => {
		useChatStore.setState({
			sessions: [sess('a1', 'A'), sess('a2', 'A')],
			activeId: 'a1',
		});
		const selectSession = vi.fn(async (id: string) => {
			useChatStore.setState({activeId: id});
		});
		useChatStore.setState({selectSession});
		await handoffHiddenActiveSession({id: 'a1', spaceId: 'A'});
		expect(selectSession).toHaveBeenCalledWith('a2');
		expect(useChatStore.getState().activeId).toBe('a2');
	});

	it('selectSession 抛错时退回 null，而不是把出口留在消失的会话上', async () => {
		useChatStore.setState({
			sessions: [sess('a1', 'A', {archived: true}), sess('a2', 'A')],
			activeId: 'a1',
		});
		useChatStore.setState({
			selectSession: vi.fn(async () => {
				throw new Error('选择会话失败');
			}),
		});
		await handoffHiddenActiveSession({id: 'a1', spaceId: 'A'});
		expect(useChatStore.getState().activeId).toBeNull();
	});

	it('selectSession 静默早退（幽灵 id）同样不留下坏落点', async () => {
		useChatStore.setState({
			sessions: [sess('a1', 'A', {archived: true}), sess('a2', 'A')],
			activeId: 'a1',
		});
		useChatStore.setState({selectSession: vi.fn(async () => undefined)});
		await handoffHiddenActiveSession({id: 'a1', spaceId: 'A'});
		expect(useChatStore.getState().activeId).toBeNull();
	});

	it('无接班人时明确置空当前会话', async () => {
		useChatStore.setState({sessions: [sess('a1', 'A')], activeId: 'a1'});
		await handoffHiddenActiveSession({id: 'a1', spaceId: 'A'});
		expect(useChatStore.getState().activeId).toBeNull();
	});
});
