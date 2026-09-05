/** 把非紧急工作放到空闲帧，避免和 rAF 打字机抢主线程。 */
export function runWhenIdle(fn: () => void): number {
	const w = window as Window & {
		requestIdleCallback?: (cb: IdleRequestCallback) => number;
	};
	if (typeof w.requestIdleCallback === 'function') {
		return w.requestIdleCallback(() => fn());
	}
	return window.setTimeout(fn, 0);
}

export function cancelWhenIdle(id: number): void {
	const w = window as Window & {
		cancelIdleCallback?: (id: number) => void;
	};
	if (typeof w.cancelIdleCallback === 'function') {
		w.cancelIdleCallback(id);
		return;
	}
	window.clearTimeout(id);
}
