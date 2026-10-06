/**
 * 单次流式发送的防抖 IDB 持久化；数据库写入与成功快照由 messageWriter
 * 串行维护，controller 负责防抖、空闲调度与 thought sync。
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
import {createMessageWriter} from '@/lib/messageWriter';
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
	const persist = createMessageWriter(seedMessages, {
		patch: msgs => patchMessages(sessionId, msgs),
		replace: msgs => replaceMessages(sessionId, msgs),
	});

	const write = (msgs: ChatMessage[]) => {
		persist(msgs);
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
