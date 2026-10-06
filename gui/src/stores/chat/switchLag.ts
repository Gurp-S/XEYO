/**
 * 会话切换「先画一帧」：把消息列表渲染用的 (activeId, 内容) 对滞后一两帧，
 * 期间由覆盖层（components/messageList/SwitchCover.tsx）盖住消息区。
 *
 * 只滞后「渲染侧」：store 的 selectSession / activeId 落点完全不动 ——
 * 乐观切换契约（首个 await 前必须已落 activeId）与滚动落点逻辑
 * （useMessageListViewport 的保存/恢复，按 activeId 触发）都按原时序跑，
 * 且 id 与内容始终成对，不会出现「新 id 配旧内容」的错位。
 */
import {useSyncExternalStore} from 'react';
import type {StoreApi} from 'zustand';
import type {ChatState} from './preStoreHelpers';

type LagState = {
	/** 追平前要显示的旧会话；null = 不滞后（直接看 store 的 activeId）。 */
	displayed: string | null;
	/** 覆盖层是否亮着。 */
	lagging: boolean;
};

let state: LagState = {displayed: null, lagging: false};
const listeners = new Set<() => void>();
let raf1 = 0;
let raf2 = 0;
let timer = 0;

function emit(): void {
	for (const l of listeners) l();
}

function resolve(): void {
	raf1 = 0;
	raf2 = 0;
	clearTimeout(timer);
	if (!state.lagging) {
		return;
	}
	state = {displayed: null, lagging: false};
	emit();
}

function begin(prevId: string): void {
	if (raf1) {
		cancelAnimationFrame(raf1);
	}
	if (raf2) {
		cancelAnimationFrame(raf2);
	}
	clearTimeout(timer);
	// 连续切换：displayed 保持最初那一屏，追平时间顺延。
	if (!state.lagging) {
		state = {displayed: prevId, lagging: true};
		emit();
	}
	raf1 = requestAnimationFrame(() => {
		raf2 = requestAnimationFrame(resolve);
	});
	// 页面隐藏时 rAF 不触发，用定时器兜底。
	timer = window.setTimeout(resolve, 160);
}

const lag = {
	get: (): LagState => state,
	subscribe: (l: () => void): (() => void) => {
		listeners.add(l);
		return () => {
			listeners.delete(l);
		};
	},
};

/** 订阅滞后状态：MessageList 取要显示的 id，覆盖层取显示与否。 */
export function useSwitchLag(): LagState {
	return useSyncExternalStore(lag.subscribe, lag.get, lag.get);
}

let installed = false;

/** 装上对 activeId 的驱动（幂等）。 */
export function installSwitchLagDriver(store: StoreApi<ChatState>): void {
	if (installed) {
		return;
	}
	installed = true;
	let lastActive: string | null = store.getState().activeId;
	store.subscribe(s => {
		const next = s.activeId;
		if (next === lastActive) {
			return;
		}
		const prev = lastActive;
		lastActive = next;
		// 首次选取（没有旧画面可盖）不滞后。
		if (prev && next) {
			begin(prev);
		}
	});
}
