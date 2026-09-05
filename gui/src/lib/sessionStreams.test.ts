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
});
