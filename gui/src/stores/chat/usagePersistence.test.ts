import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import type {StoreApi} from 'zustand';
import {saveSession} from '@/lib/db';
import {EMPTY_SESSION_STREAM} from '@/lib/sessionStreams';
import {createUsageAccumulator} from './usageAccumulator';
import type {ChatState} from './preStoreHelpers';
import type {UsageStreamEvent} from '@/lib/api';

vi.mock('@/lib/db', () => ({saveSession: vi.fn(async () => {})}));
vi.mock('@/pasture/events/PastureEvents', () => ({emitPastureEvent: vi.fn()}));

function event(overrides: Partial<UsageStreamEvent> = {}): UsageStreamEvent {
	return {kind: 'usage', promptTokens: 10, completionTokens: 2, cacheHitTokens: 4,
		cacheMissTokens: 6, tokens: 12, usedTokens: 12, usd: 0.1, usedUsd: 0.1,
		cny: 0.7, usedCny: 0.7, costSource: 'api', usdLimit: null, unpricedTurns: 0,
		budgetGateNote: '', ...overrides};
}
function fixture() {
	let state = {sessions: [{id: 's1', title: 'Fixed title', createdAt: 1, updatedAt: 1}],
		sessionUsageById: {}, sessionStreams: {s1: {...EMPTY_SESSION_STREAM, isLoading: true}},
		activeId: 'other-session'} as unknown as ChatState;
	const get = () => state;
	const set = ((update: any) => {
		state = {...state, ...(typeof update === 'function' ? update(state) : update)};
	}) as StoreApi<ChatState>['setState'];
	return {a: createUsageAccumulator(get, set, 's1'), get,
		end: () => {state.sessionStreams.s1 = {...EMPTY_SESSION_STREAM};},
		remove: () => {state.sessions = []; delete state.sessionUsageById.s1;}};
}
beforeEach(() => {
	vi.mocked(saveSession).mockReset().mockResolvedValue(undefined);
	vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-01T00:00:00Z'));
	vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
	vi.stubGlobal('cancelAnimationFrame', vi.fn());
});
afterEach(() => {vi.useRealTimers(); vi.unstubAllGlobals();});

it('saves the first request from the updated state, including a background session', () => {
	const f = fixture(); f.a.push(event()); f.a.finish(); f.end();
	expect(vi.mocked(saveSession).mock.calls).toHaveLength(1);
	expect(vi.mocked(saveSession).mock.calls[0][0].usage?.requests).toBe(1);
	expect(vi.mocked(saveSession).mock.calls[0][0].usage?.costSource).toBe('api');
});
it.each(['done', 'error', 'abort'])('persists the throttle tail at %s without waiting for the timer', () => {
	const f = fixture(); f.a.push(event()); f.a.flush();
	vi.advanceTimersByTime(100); f.a.push(event()); f.a.flush();
	f.a.finish(); f.end(); vi.advanceTimersByTime(1000);
	expect(vi.mocked(saveSession).mock.calls.at(-1)?.[0].usage?.requests).toBe(2);
	expect(vi.mocked(saveSession).mock.calls).toHaveLength(2);
});
it('finishes already-flushed state and repeated finish does not duplicate saves', () => {
	const f = fixture(); f.a.push(event()); f.a.flush();
	vi.advanceTimersByTime(100); f.a.push(event()); f.a.flush();
	f.end(); f.a.finish(); f.a.finish();
	expect(vi.mocked(saveSession).mock.calls.at(-1)?.[0].usage?.requests).toBe(2);
	expect(vi.mocked(saveSession).mock.calls).toHaveLength(2);
});
it('does not save a session removed before its deferred tail is persisted', () => {
	const f = fixture(); f.a.push(event()); f.a.flush();
	vi.advanceTimersByTime(100); f.a.push(event()); f.a.flush();
	f.remove(); f.a.finish(); vi.advanceTimersByTime(1000);
	expect(vi.mocked(saveSession).mock.calls).toHaveLength(1);
});
it('a failed save can be retried at final settlement', async () => {
	vi.mocked(saveSession).mockRejectedValueOnce(new Error('offline IDB failure'));
	const f = fixture(); f.a.push(event()); f.a.flush();
	await Promise.resolve(); await Promise.resolve();
	f.a.finish();
	expect(vi.mocked(saveSession).mock.calls).toHaveLength(2);
});
it.each([
	[['api', 'api'], 'api', 0],
	[['api', 'estimate'], 'estimate', 0],
	[['estimate', 'api'], 'estimate', 0],
	[['api', 'unpriced', 'api'], 'unpriced', 1],
	[['unpriced', 'api'], 'unpriced', 1],
] as const)('preserves cumulative price provenance for %j', (sources, expected, missing) => {
	const f = fixture();
	for (const source of sources) f.a.push(event({costSource: source, cny: source === 'unpriced' ? null : 0.7}));
	f.a.finish();
	expect(f.get().sessionUsageById.s1?.costSource).toBe(expected);
	expect(f.get().sessionUsageById.s1?.unpricedTurns).toBe(missing);
});
