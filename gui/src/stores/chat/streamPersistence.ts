/**
 * streamPersistence.ts — 单次流式发送的防抖 IDB 持久化，自
 * streamSendSlice.createStreamSendSlice() 原样拆出 (persistWrites /
 * persistNow / persistHot / persistTimer / persistIdle / fingerprints / thoughtsync)。
 * 行为不变；调用方委托给返回的 controller。
 */
import type {StoreApi} from 'zustand';
import {
	patchMessages,
	replaceMessages,
} from '@/lib/db';
import {
	cancelWhenIdle,
	runWhenIdle,
} from '@/lib/idle';
import {
	isLayoutBusy,
} from '@/lib/layoutBusy';
import {
	collectMessagesToPersist,
	seedPersistFingerprints,
} from '@/lib/messagePersist';
import {
	type ChatState,
} from './preStoreHelpers';
import {
	flushThoughtSync,
	scheduleThoughtSync,
} from './streamHelpers';
import type {
	ChatMessage,
} from '@/lib/types';

type GetState = StoreApi<ChatState>['getState'];

const IDB_DEBOUNCE_MS = 400;

export type StreamPersistence = {
	write: (msgs: ChatMessage[]) => void;
	now: (msgs: ChatMessage[]) => void;
	hot: (msgs: ChatMessage[]) => void;
	/** 镜像 clearStream 的序章：仅清除防抖计时器。 */
	cancelTimer: () => void;
	/** 镜像 clearStream 的 `else if (persistQueued)` 分支（需要 get().sessions）。 */
	flushQueued: () => void;
	/** 镜像 flushPersistOnExit 的持久化部分（queued ?? msgs + thoughtsync）。 */
	onExit: (msgs: ChatMessage[]) => void;
};

export function createStreamPersistence(deps: {
	get: GetState;
	sessionId: string;
	backendSessionId: string;
	smoothStream: () => boolean;
	seedMessages: ChatMessage[];
}): StreamPersistence {
	const {get, sessionId, backendSessionId, smoothStream, seedMessages} = deps;

	let persistTimer = 0;
	let persistIdle = 0;
	let persistQueued: ChatMessage[] | null = null;
	let persistedCount = seedMessages.length;
	let persistFingerprints = seedPersistFingerprints(seedMessages);

	const write = (msgs: ChatMessage[]) => {
		if (msgs.length < persistedCount) {
			void replaceMessages(sessionId, msgs);
			persistedCount = msgs.length;
			persistFingerprints = seedPersistFingerprints(msgs);
		} else {
			const {toWrite, nextFingerprints} = collectMessagesToPersist(
				msgs,
				persistFingerprints,
			);
			persistFingerprints = nextFingerprints;
			if (toWrite.length > 0) {
				void patchMessages(sessionId, toWrite).catch(() => {});
			}
			persistedCount = msgs.length;
		}
		scheduleThoughtSync(backendSessionId, msgs);
	};

	const now = (msgs: ChatMessage[]) => {
		persistQueued = null;
		if (persistTimer) {
			window.clearTimeout(persistTimer);
			persistTimer = 0;
		}
		if (persistIdle) {
			cancelWhenIdle(persistIdle);
			persistIdle = 0;
		}
		write(msgs);
	};

	const hot = (msgs: ChatMessage[]) => {
		if (!smoothStream()) {
			now(msgs);
			return;
		}
		persistQueued = msgs;
		if (persistTimer || persistIdle) {
			return;
		}
		persistTimer = window.setTimeout(() => {
			persistTimer = 0;
			const writeQueued = () => {
				persistIdle = 0;
				if (!persistQueued) {
					return;
				}
				if (isLayoutBusy()) {
					persistIdle = runWhenIdle(writeQueued);
					return;
				}
				const queued = persistQueued;
				persistQueued = null;
				write(queued);
			};
			persistIdle = runWhenIdle(writeQueued);
		}, IDB_DEBOUNCE_MS);
	};

	const cancelTimer = () => {
		if (persistTimer) {
			window.clearTimeout(persistTimer);
			persistTimer = 0;
		}
	};

	const flushQueued = () => {
		if (persistQueued) {
			if (get().sessions.some(s => s.id === sessionId)) {
				now(persistQueued);
			} else {
				persistQueued = null;
			}
		}
	};

	const onExit = (msgs: ChatMessage[]) => {
		const toWrite = persistQueued ?? msgs;
		now(toWrite);
		flushThoughtSync(backendSessionId, toWrite);
	};

	return {write, now, hot, cancelTimer, flushQueued, onExit};
}
