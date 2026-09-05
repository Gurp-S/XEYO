import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import type {ChatMessage, ChatSession} from '@/lib/types';
import {useChatStore} from '@/stores/chatStore';
import {setStreamingTextSignal} from '@/lib/streamSignal';
import {
	installBenchHarness,
	type BenchHarnessContext,
} from './benchHarness';
import {buildSyntheticMessages} from './syntheticTranscript';

/**
 * benchHarness 冒烟测试（jsdom）：
 * 验证 token / switch 基准的驱动逻辑、store 写入与报告组装在真实
 * 异步 rAF 下不抛错。jsdom 无真实渲染与 PerformanceObserver(longtask)，
 * 数值本身无意义，只关心「能跑通、状态自洽」。
 */

const SID_A = 'bench-smoke-a';
const SID_B = 'bench-smoke-b';

function tinyMessages(seed: number): ChatMessage[] {
	return buildSyntheticMessages({rounds: 3, seed});
}

function makeSession(id: string): ChatSession {
	const now = Date.now();
	return {
		id,
		spaceId: 'bench-smoke-space',
		title: id,
		createdAt: now,
		updatedAt: now,
	};
}

/** 真实异步帧（宏任务让出），替代 setup.ts 的同步 rAF stub。 */
function installRealRaf(): () => void {
	const realRaf = (cb: FrameRequestCallback): number =>
		window.setTimeout(() => cb(performance.now()), 0) as unknown as number;
	vi.stubGlobal('requestAnimationFrame', realRaf);
	return () => {
		vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
			cb(0);
			return 1;
		});
	};
}

describe('benchHarness smoke', () => {
	let restoreRaf: () => void;
	let ctx: BenchHarnessContext;

	beforeEach(() => {
		restoreRaf = installRealRaf();
		const aMessages = tinyMessages(11);
		const bMessages = tinyMessages(12);
		const applyState = () => {
			useChatStore.setState({
				hydrated: true,
				spaces: [
					{
						id: 'bench-smoke-space',
						name: 'smoke',
						rootPath: '',
						createdAt: 0,
						updatedAt: 0,
					},
				],
				sessions: [makeSession(SID_A), makeSession(SID_B)],
				activeId: SID_A,
				activeSpaceId: 'bench-smoke-space',
				messagesById: {[SID_A]: aMessages, [SID_B]: bMessages},
				messagesLoadingIds: {},
				sessionStreams: {},
			});
		};
		applyState();
		ctx = {
			sessionId: SID_A,
			secondarySessionId: SID_B,
			secondaryMessages: bMessages,
			primaryMessageCount: aMessages.length,
			streamText: '## 冒烟流式\n\n- 一\n- 二\n\n```ts\nconst x = 1;\n```\n\n完。',
			reset: applyState,
			finish: () => {
				setStreamingTextSignal('');
				useChatStore.setState(s => ({
					messagesById: {
						...s.messagesById,
						[SID_A]: [
							...(s.messagesById[SID_A] ?? []),
							{
								id: 'smoke-final',
								role: 'assistant',
								text: ctx.streamText,
								createdAt: Date.now(),
							},
						],
					},
					sessionStreams: {},
				}));
			},
			reinstall: null,
		};
		installBenchHarness(ctx);
	});

	afterEach(() => {
		restoreRaf();
		setStreamingTextSignal('');
		useChatStore.setState({sessionStreams: {}, messagesLoadingIds: {}});
	});

	it('runTokenBench 跑通且流状态自洽（收尾时无残留 isLoading）', async () => {
		const result = await window.__XY_BENCH__!.runTokenBench({
			seconds: 0.2,
			charsPerFrame: 4,
		});
		expect(result.frameDelta.n).toBeGreaterThan(0);
		// jsdom 无 <Profiler> 挂载 → 无提交采集，属预期；接线在下一个用例覆盖。
		expect(result.commit.n).toBe(0);
		expect(result.settle.settleMs).toBeGreaterThanOrEqual(0);
		const stream = useChatStore.getState().sessionStreams[SID_A];
		expect(stream?.isLoading ?? false).toBe(false);
		// settle 后全文落盘为最后一条 assistant 消息。
		const msgs = useChatStore.getState().messagesById[SID_A]!;
		expect(msgs[msgs.length - 1]!.text).toBe(ctx.streamText);
	}, 20000);

	it('runSwitchBench warm 往返后 B 无 loading 残留（cold 收尾停在 B 属预期）', async () => {
		// jsdom 无 IDB：cold 装载不可能完成，把 cold 超时调短以免白等。
		const result = await window.__XY_BENCH__!.runSwitchBench({
			pairs: 1,
			coldTimeoutMs: 300,
		});
		expect(result.warm.samples).toBe(2);
		expect(result.cold).not.toBeNull();
		const state = useChatStore.getState();
		expect(state.messagesLoadingIds[SID_B]).toBeFalsy();
	}, 20000);

	it('Profiler 接线：startBenchCommits 后 onRender 采集，drain 后清空', async () => {
		const {onBenchProfilerRender, startBenchCommits, drainBenchCommits, stopBenchCommits, setBenchPhase} =
			await import('./benchProfiler');
		setBenchPhase('token');
		startBenchCommits();
		onBenchProfilerRender('xy-bench-chatpage', 'update', 3.5, 10, 0, 1);
		onBenchProfilerRender('xy-bench-chatpage', 'update', 1.5, 10, 0, 2);
		const drained = drainBenchCommits();
		stopBenchCommits();
		expect(drained).toHaveLength(2);
		expect(drained[0]).toMatchObject({
			benchPhase: 'token',
			profilerId: 'xy-bench-chatpage',
			actualDuration: 3.5,
		});
		expect(drainBenchCommits()).toHaveLength(0);
	}, 20000);
});
