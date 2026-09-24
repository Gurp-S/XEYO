import {describe, expect, it} from 'vitest';
import {
	getSessionStream,
	isSessionStreamLive,
	normalizeSessionStreams,
	patchSessionStream,
	selectRunningSessionIds,
	selectRunningSessionKey,
	sessionStreamActive,
} from '@/lib/sessionStreams';

describe('sessionStreams', () => {
	it('tolerates missing sessionStreams map', () => {
		expect(getSessionStream(undefined, 's1').isLoading).toBe(false);
		expect(sessionStreamActive(undefined, 's1')).toBe(false);
		expect(selectRunningSessionIds(undefined)).toEqual([]);
	});

	it('migrates legacy global streaming fields', () => {
		const map = normalizeSessionStreams({
			streamingSessionId: 'legacy',
			isLoading: true,
			streamingText: 'hello',
			statusText: 'thinking…',
		});
		expect(map.legacy?.isLoading).toBe(true);
		expect(map.legacy?.streamingText).toBe('hello');
	});

	it('selectRunningSessionKey is stable for same running set', () => {
		const state = {
			sessionStreams: {
				a: {isLoading: true, draining: false} as never,
				b: {isLoading: false, draining: true} as never,
				c: {isLoading: false, draining: false} as never,
			},
		};
		expect(selectRunningSessionKey(state)).toBe('a\0b');
		expect(selectRunningSessionKey(state)).toBe(selectRunningSessionKey(state));
	});

	it('patchSessionStream accepts undefined prev', () => {
		const next = patchSessionStream(undefined, 's1', {isLoading: true});
		expect(next.s1?.isLoading).toBe(true);
	});

	it('isSessionStreamLive treats drain and live abort as live, ghost locks as dead', () => {
		const liveAbort = new AbortController();
		const deadAbort = new AbortController();
		deadAbort.abort();
		expect(
			isSessionStreamLive({
				...getSessionStream(undefined, 'x'),
				draining: true,
				abortRef: null,
			}),
		).toBe(true);
		expect(
			isSessionStreamLive({
				...getSessionStream(undefined, 'x'),
				isLoading: true,
				abortRef: liveAbort,
			}),
		).toBe(true);
		expect(
			isSessionStreamLive({
				...getSessionStream(undefined, 'x'),
				isLoading: true,
				abortRef: deadAbort,
			}),
		).toBe(false);
		expect(
			isSessionStreamLive({
				...getSessionStream(undefined, 'x'),
				isLoading: true,
				abortRef: null,
			}),
		).toBe(false);
		expect(
			isSessionStreamLive({
				...getSessionStream(undefined, 'x'),
				remoteStreaming: true,
				abortRef: null,
			}),
		).toBe(true);
	});

	it('keeps the detached marker alive while the visible fields go quiet', () => {
		// 后端仍在跑、本页 SSE 已断：任何只清文案的 patch 都不能顺手把
		// turnDetached 抹掉——否则 recoverStuckStream 会把仍在跑的轮次判成中断。
		let map = patchSessionStream(undefined, 's1', {
			isLoading: true,
			statusText: 'thinking…',
		});
		map = patchSessionStream(map, 's1', {turnDetached: true, lastEventId: 42});
		map = patchSessionStream(map, 's1', {isLoading: false, statusText: ''});
		const detached = map['s1'];
		expect(detached?.turnDetached).toBe(true);
		expect(detached?.lastEventId).toBe(42);
		expect(isSessionStreamLive(detached!)).toBe(true);
		// 解除标记后条目必须重新可回收，不能留成永久脏记录。
		expect(patchSessionStream(map, 's1', {turnDetached: false})['s1']).toBeUndefined();
	});
});
