/**
 * benchProfiler.ts — /bench/chat 专用 React Profiler 采集（P0 测量设施）。
 *
 * OfflineReplayRoute 在 bench 模式下用 <Profiler onRender> 包住 <ChatPage/>，
 * 把每次提交的 actualDuration 按「当前基准阶段」归档。生产构建与普通
 * 路由不会挂载该 Profiler；采集关闭时回调是纯 no-op。
 */

import type {ProfilerOnRenderCallback} from 'react';

export type BenchCommit = {
	/** 采集时的基准阶段（token / token-warmup / settle / switch-warm / switch-cold / scroll…）。 */
	benchPhase: string;
	profilerId: string;
	/** React 本次提交的实际渲染耗时（ms）。 */
	actualDuration: number;
	/** 提交时间轴（performance origin），用于与 mark 对齐。 */
	commitTime: number;
};

const MAX_COMMITS = 60000;

let currentPhase = 'idle';
let collecting = false;
const commits: BenchCommit[] = [];

export function setBenchPhase(phase: string): void {
	currentPhase = phase;
}

export function getBenchPhase(): string {
	return currentPhase;
}

export function startBenchCommits(): void {
	commits.length = 0;
	collecting = true;
}

export function stopBenchCommits(): void {
	collecting = false;
}

/** 取走全部已采集提交（调用后清空）。 */
export function drainBenchCommits(): BenchCommit[] {
	const out = commits.slice();
	commits.length = 0;
	return out;
}

export function benchCommitCount(): number {
	return commits.length;
}

export const onBenchProfilerRender: ProfilerOnRenderCallback = (
	profilerId,
	_phase,
	actualDuration,
	_baseDuration,
	_startTime,
	commitTime,
) => {
	if (!collecting || commits.length >= MAX_COMMITS) {
		return;
	}
	commits.push({
		benchPhase: currentPhase,
		profilerId,
		actualDuration,
		commitTime,
	});
};
