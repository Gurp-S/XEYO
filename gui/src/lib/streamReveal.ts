/** A fixed time budget for each received prefix, independent of refresh rate. */
export const STREAM_REVEAL_MS = 100;

export function createStreamReveal(
	durationMs = STREAM_REVEAL_MS,
	now: () => number = () => performance.now(),
): (backlog: number, shown: number) => number {
	let window: {from: number; to: number; start: number} | undefined;
	return (backlog, shown) => {
		const time = now();
		const total = shown + backlog;
		if (!window || shown < window.from || total < window.to || shown >= window.to) {
			window = {from: shown, to: total, start: time};
			// The first received character is visible in the same state update.
			return Math.min(1, backlog);
		}
		// Appends do not move this prefix's deadline. A continuous fast stream
		// therefore cannot keep postponing text that has already arrived.
		const progress = Math.min(1, Math.max(0, (time - window.start) / durationMs));
		return Math.max(0, Math.ceil(window.from + (window.to - window.from) * progress) - shown);
	};
}
