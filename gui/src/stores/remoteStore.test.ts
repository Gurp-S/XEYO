import {beforeEach, describe, expect, it, vi} from 'vitest';
import {pollIssueFromStatus, streamingFlagUpdate, useRemoteStore} from './remoteStore';
import {resetRemoteMirrorSession} from '@/lib/remoteSession';

describe('pollIssueFromStatus', () => {
	it('ignores empty long-poll timeout', () => {
		expect(pollIssueFromStatus({last_poll_error: 'timeout'})).toBeNull();
		expect(pollIssueFromStatus({last_poll_error: null, hint: 'ClawBot / iLink 已连接'})).toBeNull();
	});

	it('surfaces transport failures and gateway hint', () => {
		expect(
			pollIssueFromStatus({last_poll_error: 'transport:ConnectError:proxy'}),
		).toBe('transport:ConnectError:proxy');
		expect(
			pollIssueFromStatus({
				last_poll_error: 'timeout',
				hint: '连不上微信网关，请检查网络或系统代理是否已启动',
			}),
		).toContain('连不上微信网关');
		expect(
			pollIssueFromStatus({
				error: '回复未能发到微信：TimeoutException: read',
			}),
		).toContain('回复未能发到微信');
	});
});

describe('streamingFlagUpdate', () => {
	it('skips patch when already streaming', () => {
		expect(streamingFlagUpdate(true, true)).toBeUndefined();
		expect(streamingFlagUpdate(false, false)).toBeUndefined();
		expect(streamingFlagUpdate(false, true)).toEqual({streaming: true});
		expect(streamingFlagUpdate(true, false)).toEqual({streaming: false});
	});
});

describe('applySseDelta streaming flag', () => {
	beforeEach(() => {
		resetRemoteMirrorSession();
		useRemoteStore.setState({streaming: false});
		useRemoteStore.getState().handleSsePayload('delta', {streaming: false});
	});

	it('sets streaming once on first delta', () => {
		expect(useRemoteStore.getState().streaming).toBe(false);
		useRemoteStore.getState().handleSsePayload('delta', {
			streaming: true,
			text: 'ab',
			len: 2,
		});
		expect(useRemoteStore.getState().streaming).toBe(true);
	});

	it('does not setState when already streaming', () => {
		useRemoteStore.getState().handleSsePayload('delta', {
			streaming: true,
			text: 'ab',
			len: 2,
		});
		expect(useRemoteStore.getState().streaming).toBe(true);

		let n = 0;
		const unsub = useRemoteStore.subscribe(() => {
			n += 1;
		});
		useRemoteStore.getState().handleSsePayload('delta', {
			streaming: true,
			text: 'abcd',
			len: 4,
		});
		expect(n).toBe(0);
		expect(useRemoteStore.getState().streaming).toBe(true);
		unsub();
	});

	it('ignores delta from another WeChat session', () => {
		resetRemoteMirrorSession();
		useRemoteStore.setState({streaming: false});
		useRemoteStore.getState().handleSsePayload('event', {
			id: 'ev-a',
			kind: 'inbound',
			text: 'from-a',
			session_id: 'ilink:a',
		});
		useRemoteStore.getState().handleSsePayload('delta', {
			streaming: true,
			text: 'aaa',
			len: 3,
			session_id: 'ilink:a',
		});
		expect(useRemoteStore.getState().streaming).toBe(true);
		let n = 0;
		const unsub = useRemoteStore.subscribe(() => {
			n += 1;
		});
		useRemoteStore.getState().handleSsePayload('delta', {
			streaming: true,
			text: 'bbb',
			len: 3,
			session_id: 'ilink:b',
		});
		expect(n).toBe(0);
		unsub();
	});
});

describe('remote tool SSE', () => {
	beforeEach(() => {
		resetRemoteMirrorSession();
	});

	it('routes tool_call SSE to chatStore', async () => {
		const {useChatStore} = await import('./chatStore');
		const applyRemoteToolCall = vi.fn();
		useChatStore.setState({applyRemoteToolCall});
		useRemoteStore.getState().handleSsePayload('tool', {
			id: 'tool-1',
			kind: 'tool_call',
			name: 'Screenshot',
			input: {monitor: 1},
		});
		expect(applyRemoteToolCall).toHaveBeenCalledWith('Screenshot', {
			monitor: 1,
		});
	});

	it('ignores tool SSE from another WeChat session', async () => {
		const {useChatStore} = await import('./chatStore');
		const applyRemoteToolCall = vi.fn();
		useChatStore.setState({applyRemoteToolCall});
		useRemoteStore.getState().handleSsePayload('event', {
			id: 'ev-mirror-a',
			kind: 'inbound',
			text: 'from-a',
			session_id: 'ilink:a',
		});
		useRemoteStore.getState().handleSsePayload('tool', {
			id: 'tool-b',
			kind: 'tool_call',
			name: 'Bash',
			input: {command: 'pwd'},
			session_id: 'ilink:b',
		});
		expect(applyRemoteToolCall).not.toHaveBeenCalled();
	});
});
