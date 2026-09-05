/**
 * usageAccumulator.ts — per-stream usage accounting, extracted verbatim from
 * streamSendSlice.createStreamSendSlice() flushUsage/scheduleUsage/pendingUsage.
 * Behavior unchanged; the onUsage stream handler delegates to push().
 */
import type {StoreApi} from 'zustand';
import {
	type CompressionStreamEvent,
	type UsageStreamEvent,
} from '@/lib/api';
import {
	saveSession,
} from '@/lib/db';
import {
	sessionStreamActive,
} from '@/lib/sessionStreams';
import {
	emitPastureEvent,
} from '@/pasture/events/PastureEvents';
import {
	type ChatState,
} from './preStoreHelpers';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];

export type UsageAccumulator = {
	flush: () => void;
	schedule: () => void;
	/** 追加一条 usage 事件并调度 rAF 冲刷（守卫由调用方处理）。 */
	push: (ev: UsageStreamEvent) => void;
	/** 完整 onUsage 分发：守卫 + pasture 语境快照 + 调度冲刷。 */
	onUsage: (ev: UsageStreamEvent) => void;
	/** 完整 onCompression 分发：pasture 压缩开始/完成的快照。 */
	onCompression: (ev: Omit<CompressionStreamEvent, 'kind'>) => void;
};

export function createUsageAccumulator(
	get: GetState,
	set: SetState,
	sessionId: string,
): UsageAccumulator {
	let usageRaf = 0;
	let pendingUsage: UsageStreamEvent[] = [];
	// 流式期间 usage 落盘节流(2026-09-05 排查):flush 是 RAF 合并的,usage 事件
	// 密集时原本每帧都可能 saveSession 一次。限 2 次/秒,窗口尾部补一次防丢尾。
	let lastPersistAt = 0;
	let persistTimer: ReturnType<typeof setTimeout> | undefined;

	const persistSessionUsage = () => {
		const cur = get();
		const sess = cur.sessions.find(s => s.id === sessionId);
		const usage = cur.sessionUsageById[sessionId];
		if (!sess || !usage || !sessionStreamActive(cur, sessionId)) {
			return;
		}
		void saveSession({...sess, usage, updatedAt: Date.now()});
	};

	const scheduleUsagePersist = () => {
		const now = Date.now();
		const elapsed = now - lastPersistAt;
		if (elapsed >= 500) {
			lastPersistAt = now;
			if (persistTimer !== undefined) {
				clearTimeout(persistTimer);
				persistTimer = undefined;
			}
			persistSessionUsage();
			return;
		}
		if (persistTimer === undefined) {
			persistTimer = setTimeout(() => {
				persistTimer = undefined;
				lastPersistAt = Date.now();
				persistSessionUsage();
			}, 500 - elapsed);
		}
	};

	const flush = () => {
		if (usageRaf) {
			cancelAnimationFrame(usageRaf);
			usageRaf = 0;
		}
		if (pendingUsage.length === 0 || !sessionStreamActive(get(), sessionId)) {
			pendingUsage = [];
			return;
		}
		const events = pendingUsage;
		pendingUsage = [];
		const current = get();
		const previous = current.sessionUsageById[sessionId];
		let nextUsage = previous;
		for (const ev of events) {
			const hasContextTokens = typeof ev.contextTokens === 'number';
			const hasContextLimit = typeof ev.contextLimit === 'number' && ev.contextLimit > 0;
			const estimated = (
				nextUsage?.costSource === 'unknown' ||
				ev.costSource === 'unknown'
			);
			nextUsage = {
				promptTokens: (nextUsage?.promptTokens ?? 0) + ev.promptTokens,
				completionTokens: (nextUsage?.completionTokens ?? 0) + ev.completionTokens,
				cacheHitTokens: (nextUsage?.cacheHitTokens ?? 0) + ev.cacheHitTokens,
				cacheMissTokens: (nextUsage?.cacheMissTokens ?? 0) + ev.cacheMissTokens,
				tokens: (nextUsage?.tokens ?? 0) + ev.tokens,
				cny: (nextUsage?.cny ?? 0) + ev.cny,
				requests: (nextUsage?.requests ?? 0) + 1,
				costSource:
					estimated
						? 'unknown'
						: nextUsage?.costSource === 'api' && ev.costSource === 'api'
						? 'api'
						: 'estimate',
				usdLimit: ev.usdLimit,
				contextTokens: hasContextTokens ? ev.contextTokens : nextUsage?.contextTokens,
				// smoke-test #2：事件未带窗口时清空而非沿用旧值 —— 换模型后
				// 旧窗口不会残留（显示"窗口未知"比显示错误窗口更诚实）。
				contextLimit: hasContextLimit ? ev.contextLimit : undefined,
				contextPercent:
					hasContextTokens && hasContextLimit
						? Math.min(100, Math.max(0, (ev.contextTokens! / ev.contextLimit!) * 100))
						: nextUsage?.contextPercent,
				contextSource: hasContextTokens ? 'stream' : nextUsage?.contextSource,
				dataQuality: hasContextTokens && hasContextLimit ? 'measured' : nextUsage?.dataQuality,
				lastContextAt: hasContextTokens ? Date.now() : nextUsage?.lastContextAt,
				contextBreakdown: ev.contextBreakdown?.length
					? ev.contextBreakdown
					: nextUsage?.contextBreakdown,
				// 单轮（非累计）拆分：与 contextTokens 同轮，供「上下文构成」回退条
				// 使用；累计值会超过窗口，不能拿来画本轮构成。
				lastCacheHitTokens: ev.cacheHitTokens,
				lastCacheMissTokens: ev.cacheMissTokens,
				lastCompletionTokens: ev.completionTokens,
				compactCursor:
					typeof ev.compactCursor === 'number'
						? ev.compactCursor
						: nextUsage?.compactCursor,
				lastAction: ev.lastAction || nextUsage?.lastAction,
				c2SummaryChars:
					typeof ev.c2SummaryChars === 'number'
						? ev.c2SummaryChars
						: nextUsage?.c2SummaryChars,
			};
		}
		if (!nextUsage) {
			return;
		}
		const nextSession = current.sessions.find(s => s.id === sessionId);
		if (nextSession) {
			const persisted = {...nextSession, usage: nextUsage, updatedAt: Date.now()};
			scheduleUsagePersist();
			set(state => ({
				sessions: state.sessions.map(s => s.id === sessionId ? persisted : s),
				sessionUsageById: {...state.sessionUsageById, [sessionId]: nextUsage},
			}));
		} else {
			set(state => ({
				sessionUsageById: {...state.sessionUsageById, [sessionId]: nextUsage},
			}));
		}
	};

	const schedule = () => {
		if (!usageRaf) {
			usageRaf = requestAnimationFrame(flush);
		}
	};

	const push = (ev: UsageStreamEvent) => {
		pendingUsage.push(ev);
		schedule();
	};

	const onUsage = (ev: UsageStreamEvent) => {
		if (!sessionStreamActive(get(), sessionId)) {
			return;
		}
		if (typeof ev.contextTokens === 'number' || typeof ev.contextLimit === 'number') {
			emitPastureEvent({
				type: 'CONTEXT_UPDATE',
				sessionId,
				snapshot: {
					currentTokens: ev.contextTokens,
					contextLimit: ev.contextLimit,
					usagePercent:
						typeof ev.contextTokens === 'number' &&
						typeof ev.contextLimit === 'number' && ev.contextLimit > 0
							? (ev.contextTokens / ev.contextLimit) * 100
							: undefined,
					contextSource: 'stream',
					dataQuality: 'measured',
					lastUpdatedAt: Date.now(),
					isStale: false,
				},
			});
		}
		push(ev);
	};

	const onCompression = (ev: Omit<CompressionStreamEvent, 'kind'>) => {
		if (!sessionStreamActive(get(), sessionId)) return;
		const snapshot = {
			currentTokens: ev.contextTokens,
			contextLimit: ev.contextLimit,
			usagePercent:
				typeof ev.contextTokens === 'number' &&
				typeof ev.contextLimit === 'number' && ev.contextLimit > 0
					? (ev.contextTokens / ev.contextLimit) * 100
					: undefined,
			contextSource: 'stream' as const,
			dataQuality: 'measured' as const,
			lastUpdatedAt: Date.now(),
			isStale: false,
		};
		if (ev.phase === 'start') {
			emitPastureEvent({type: 'CONTEXT_COMPRESSION_START', sessionId, source: ev.source});
		} else {
			emitPastureEvent({
				type: 'CONTEXT_COMPRESSION_COMPLETE',
				sessionId,
				source: ev.source,
				snapshot,
			});
		}
	};

	return {flush, schedule, push, onUsage, onCompression};
}
