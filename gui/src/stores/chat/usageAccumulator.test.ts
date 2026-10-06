import {afterEach, describe, expect, it, vi} from 'vitest';
import type {StoreApi} from 'zustand';
import type {UsageStreamEvent} from '@/lib/api';
import {EMPTY_SESSION_STREAM} from '@/lib/sessionStreams';
import type {ChatState} from './preStoreHelpers';
import {createUsageAccumulator} from './usageAccumulator';

function usageEvent(overrides: Partial<UsageStreamEvent> = {}): UsageStreamEvent {
	return {
		kind: 'usage' as const,
		promptTokens: 10,
		completionTokens: 2,
		cacheHitTokens: 4,
		cacheMissTokens: 6,
		tokens: 12,
		usedTokens: 12,
		usd: 0,
		usedUsd: 0,
		cny: 0,
		usedCny: 0,
		costSource: 'api' as const,
		usdLimit: null,
		unpricedTurns: 0,
		budgetGateNote: '',
		...overrides,
	};
}

function makeAccumulator(initialUsage?: Record<string, unknown>) {
	let state = {
		sessions: [],
		sessionUsageById: initialUsage ? {s1: initialUsage} : {},
		sessionStreams: {s1: {...EMPTY_SESSION_STREAM, isLoading: true}},
	} as unknown as ChatState;
	const get = () => state;
	const set = ((updater: unknown) => {
		const next = typeof updater === 'function'
			? (updater as (current: ChatState) => Partial<ChatState>)(state)
			: (updater as Partial<ChatState>);
		state = {...state, ...next};
	}) as StoreApi<ChatState>['setState'];
	return {
		accumulator: createUsageAccumulator(get, set, 's1'),
		read: () => state.sessionUsageById.s1,
	};
}

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('createUsageAccumulator · 最近请求上下文快照', () => {
	it('新请求缺上下文遥测时清除旧快照，同时保留会话累计用量', () => {
		vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
		vi.stubGlobal('cancelAnimationFrame', vi.fn());
		const {accumulator, read} = makeAccumulator({
			promptTokens: 100,
			completionTokens: 20,
			cacheHitTokens: 40,
			cacheMissTokens: 60,
			tokens: 120,
			cny: 0,
			requests: 1,
			costSource: 'api',
			contextTokens: 100,
			contextLimit: 200,
			contextPercent: 50,
			contextSource: 'stream',
			dataQuality: 'measured',
			lastContextAt: 123,
			contextBreakdown: [{category: 'conversation', label: '对话', tokens: 100}],
		});

		accumulator.push(usageEvent());
		accumulator.flush();

		const usage = read();
		expect(usage?.requests).toBe(2);
		expect(usage?.tokens).toBe(132);
		expect(usage?.contextTokens).toBeUndefined();
		expect(usage?.contextLimit).toBeUndefined();
		expect(usage?.contextPercent).toBeUndefined();
		expect(usage?.contextBreakdown).toBeUndefined();
	});
});
