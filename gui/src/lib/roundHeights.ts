/** 聊天轮次实测高度的缓存——供占位块与 content-visibility 使用。 */

const heights = new Map<string, number>();

const DEFAULT_ROUND_HEIGHT = 120;

/** 每次实际写入/清除高度时递增；VirtualRoundList 借此判断前缀和是否失效。 */
let version = 0;

const listeners = new Set<() => void>();

export function getRoundHeight(roundId: string): number | undefined {
	return heights.get(roundId);
}

export function getRoundHeightOrDefault(roundId: string): number {
	return heights.get(roundId) ?? DEFAULT_ROUND_HEIGHT;
}

export function getRoundHeightsVersion(): number {
	return version;
}

/**
 * 订阅高度变化（VirtualRoundList 重算前缀和 / 窗口）。
 * 回调在 ResizeObserver 回调里同步触发，订阅方必须自行做帧合并，
 * 且不得在回调里同步写 React state。
 */
export function subscribeRoundHeights(cb: () => void): () => void {
	listeners.add(cb);
	return () => {
		listeners.delete(cb);
	};
}

function notify(): void {
	version += 1;
	for (const listener of listeners) {
		listener();
	}
}

export function setRoundHeight(roundId: string, height: number): void {
	if (!(height > 0) || !Number.isFinite(height)) {
		return;
	}
	const rounded = Math.round(height);
	const prev = heights.get(roundId);
	if (prev === rounded) {
		return;
	}
	heights.set(roundId, rounded);
	notify();
}

export function clearRoundHeight(roundId: string): void {
	if (!heights.delete(roundId)) {
		return;
	}
	notify();
}
