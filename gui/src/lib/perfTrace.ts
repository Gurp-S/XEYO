type PerfTraceWindow = Window & {
	__XY_PERF_TRACE__?: boolean;
};

function enabled(): boolean {
	return typeof window !== 'undefined' && Boolean((window as PerfTraceWindow).__XY_PERF_TRACE__);
}

export function perfMark(name: string): void {
	if (!enabled() || typeof performance === 'undefined') return;
	performance.mark(`xy:${name}`);
}

export function perfMeasure(name: string, start: string): void {
	if (!enabled() || typeof performance === 'undefined') return;
	const startMark = `xy:${start}`;
	const endMark = `xy:${name}:end`;
	performance.mark(endMark);
	try {
		performance.measure(`xy:${name}`, startMark, endMark);
	} catch {
		// 过期的标记绝不应影响渲染或交互。
	}
	performance.clearMarks(startMark);
	performance.clearMarks(endMark);
}

export function perfTrace<T>(name: string, fn: () => T): T {
	if (!enabled() || typeof performance === 'undefined') return fn();
	const start = `${name}:start`;
	perfMark(start);
	try {
		return fn();
	} finally {
		perfMeasure(name, start);
	}
}
