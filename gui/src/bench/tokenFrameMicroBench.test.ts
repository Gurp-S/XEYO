import {describe, expect, it} from 'vitest';
import {buildSyntheticMessages} from './syntheticTranscript';
import {groupTranscript, patchTranscriptTail} from '@/lib/groupTranscript';
import {
	groupRounds,
	reuseRoundPrefix,
	roundsWithAgentTasks,
} from '@/components/messageList/groupRounds';
import {computeRoundPrefix} from '@/lib/roundVirtual';

/**
 * token 帧微基准（P0 基线报告的 JS 侧证据，node/vitest 实测、可复现）。
 *
 * 模拟流式直播期间每 token 帧的 O(rounds) 管线（不含 React 渲染与绘制）：
 *   patchTranscriptTail → groupRounds → reuseRoundPrefix →
 *   roundsWithAgentTasks → rounds.map(id) → computeRoundPrefix
 *
 * 输出 console.table（p50/p95，ms）；断言只锁功能不变量，
 * 不锁耗时（避免 flaky）。数字解读见 BASELINE.md §3。
 */

const SIZES = [500, 2000, 5000];
const FRAMES = 120;
const STREAM_SAMPLE = '这是模拟流式尾部，一帧推进几个码点。'.repeat(3);

function stats(values: number[]): {p50: number; p95: number; max: number} {
	const sorted = [...values].sort((a, b) => a - b);
	const at = (q: number): number =>
		sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]!;
	return {p50: at(0.5), p95: at(0.95), max: sorted[sorted.length - 1]!};
}

function bench(fn: () => void, times: number): number[] {
	for (let i = 0; i < 5; i += 1) {
		fn();
	}
	const out: number[] = [];
	for (let i = 0; i < times; i += 1) {
		const t0 = performance.now();
		fn();
		out.push(performance.now() - t0);
	}
	return out;
}

describe('token 帧微基准（JS 侧，不含 React/绘制）', () => {
	it.for(SIZES)('rounds=%d：逐阶段测耗时', {timeout: 120_000}, size => {
		const messages = buildSyntheticMessages({rounds: size, seed: 20240501});

		// 会话装载路径：全量分组（每次进会话 / blocks 缓存未命中时一次）。
		const mountStats = stats(bench(() => {
			const blocks = groupTranscript(messages);
			expect(blocks.length).toBeGreaterThan(size);
		}, 20));

		const blocks = groupTranscript(messages);
		const settled = patchTranscriptTail(blocks, {isLoading: false});
		const baseRounds = groupRounds(settled);
		const baseIds = baseRounds.map(r => r.id);

		let roundsPrev: ReturnType<typeof groupRounds> | null = null;
		let frame = 0;
		const perFrame = bench(() => {
			// 1) 流式尾 patch（messages 引用未变，只改尾巴）。
			const tail = STREAM_SAMPLE.slice(0, (frame % STREAM_SAMPLE.length) + 1);
			const patched = patchTranscriptTail(settled, {
				isLoading: true,
				streamingText: tail,
			});
			// 2) 全量重分组 + 前缀复用。
			const grouped = reuseRoundPrefix(roundsPrev, groupRounds(patched));
			// 3) agentTasks 绑定（无任务时的短路检查）。
			const withTasks = roundsWithAgentTasks(grouped, undefined);
			// 4) roundIds 全量 map。
			const ids = withTasks.map(r => r.id);
			// 5) 前缀和全量重算（VirtualRoundList ensurePrefix）。
			const prefix = computeRoundPrefix(ids);
			expect(prefix.length).toBe(ids.length + 1);
			roundsPrev = withTasks;
			frame += 1;
		}, FRAMES);
		const frameStats = stats(perFrame);

		// 单独看前缀和（roundIds 引用变化时每帧都重算）。
		const prefixOnly = stats(bench(() => {
			computeRoundPrefix(baseIds);
		}, FRAMES));

		console.table([
			{name: 'groupTranscript 全量（装载一次）', p50: mountStats.p50, p95: mountStats.p95, max: mountStats.max},
			{name: 'token 帧全管线（1-5 连跑）', p50: frameStats.p50, p95: frameStats.p95, max: frameStats.max},
			{name: '其中：computeRoundPrefix', p50: prefixOnly.p50, p95: prefixOnly.p95, max: prefixOnly.max},
		]);

		// 功能不变量：管线输出形状稳定。
		expect(baseRounds.length).toBe(size);
		expect(baseIds.length).toBe(size);
	});
});
