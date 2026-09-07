/**
 * streamDrain.ts — 流结束后的打字机收尾排水逻辑，自
 * streamSendSlice.createStreamSendSlice() 原样拆出
 * (drainFrame/startDrain/finish/discard /
 * drainTextSnap / drainMode)。行为不变；commitAssistant 通过
 * getTextSnap()/isDraining() 读取排水后的快照。
 */
import type {StoreApi} from 'zustand';
import {
	advanceTypewriterShown,
	drainTypewriterStep,
	type TypewriterAdvanceCache,
} from '@/hooks/useStreamTypewriter';
import {
	getSessionStream,
	patchSessionStream,
} from '@/lib/sessionStreams';
import {
	setStreamingTextSignal,
	streamSignalsEnabled,
} from '@/lib/streamSignal';
import {
	activeDrains,
	type ChatState,
} from './preStoreHelpers';
import {
	appendAssistantProse,
	todosWithUnfinished,
} from './streamHelpers';
import type {
	ChatMessage,
} from '@/lib/types';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];

export type StreamDrain = {
	start: () => void;
	finish: () => void;
	discard: () => void;
	getTextSnap: () => string;
	isDraining: () => boolean;
};

export function createStreamDrain(deps: {
	get: GetState;
	set: SetState;
	sessionId: string;
	typewriterCache: TypewriterAdvanceCache;
	persistNow: (msgs: ChatMessage[]) => void;
	sessionStillAlive: () => boolean;
	cancelFrameRaf: () => void;
	onFinish: () => void;
}): StreamDrain {
	const {get, set, sessionId, typewriterCache, persistNow, sessionStillAlive, cancelFrameRaf, onFinish} = deps;

	let drainRaf = 0;
	// 排水快照：onDone 时流式输出已完整；startDrain 释放 streamingSessionId
	// 前先存下全文，commitAssistant 靠它落盘（见 drained 分支）。
	let drainTextSnap = '';
	let drainMode = false;

	const releaseDrainOwnership = () => {
		activeDrains.delete(sessionId);
		if (drainRaf) {
			cancelAnimationFrame(drainRaf);
			drainRaf = 0;
		}
	};
	const finishDrain = () => {
		releaseDrainOwnership();
		onFinish();
	};
	const discardDrain = () => {
		releaseDrainOwnership();
		drainMode = false;
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				streamingText: '',
				streamingShown: '',
				draining: false,
			}),
		}));
		if (streamSignalsEnabled && get().activeId === sessionId) {
			setStreamingTextSignal('');
		}
	};
	const drainFrame = () => {
		drainRaf = 0;
		if (!activeDrains.has(sessionId)) {
			return;
		}
		const cur = get();
		const stream = getSessionStream(cur, sessionId);
		const target = stream.streamingText;
		if (!target || !target.startsWith(stream.streamingShown)) {
			finishDrain();
			return;
		}
		const next = advanceTypewriterShown(
			target,
			stream.streamingShown,
			typewriterCache,
			drainTypewriterStep,
			// 排水是收尾路径：必须允许追平（否则标号被扣住后 shown 永远差一口气，drain 停不下来）
			false,
		);
		if (next !== stream.streamingShown) {
			set(s => ({
				sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
					streamingShown: next,
				}),
			}));
			if (streamSignalsEnabled && get().activeId === sessionId) {
				setStreamingTextSignal(next);
			}
		}
		if (next === target) {
			finishDrain();
			return;
		}
		drainRaf = requestAnimationFrame(drainFrame);
	};
	const start = () => {
		drainTextSnap = getSessionStream(get(), sessionId).streamingText;
		drainMode = true;
		if (drainTextSnap.trim() && sessionStillAlive()) {
			const cur = get();
			// 保留已稳定的 Thought 行，仅提前挂上 prose 供排水展示
			const msgs = appendAssistantProse(
				cur.messagesById[sessionId] ?? [],
				drainTextSnap,
			);
			set(s => ({
				messagesById: {...s.messagesById, [sessionId]: msgs},
			}));
			persistNow(msgs);
		}
		activeDrains.set(sessionId, {
			commit: finishDrain,
			discard: discardDrain,
		});
		cancelFrameRaf();
		const cur = get();
		set(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
				isLoading: false,
				statusText: '',
				abortRef: null,
				draining: true,
			}),
			pendingPlan:
				s.pendingPlan?.sessionId === sessionId ? null : s.pendingPlan,
			// smoke-test #1：排水开始不清空未完成 todo 面板。
			sessionTodosById: {
				...cur.sessionTodosById,
				[sessionId]: todosWithUnfinished(
					cur.sessionTodosById[sessionId],
				),
			},
		}));
		drainRaf = requestAnimationFrame(drainFrame);
	};

	return {
		start,
		finish: finishDrain,
		discard: discardDrain,
		getTextSnap: () => drainTextSnap,
		isDraining: () => drainMode,
	};
}
