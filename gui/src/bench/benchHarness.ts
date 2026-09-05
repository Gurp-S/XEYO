/**
 * benchHarness.ts — /bench/chat 性能基准执行器（P0 测量设施）。
 *
 * 用法：dev server 起来后打开 `/bench/chat?rounds=5000&bench=1`，在 DevTools
 * console 执行 `await __XY_BENCH__.runAll()`。报告同时 return 与打印；
 * `__XY_BENCH__.download()` 落一份 JSON 便于归档对比。
 *
 * 三个基准（预算来自 P0 计划，最终以用户确认为准）：
 * - token 帧   ：流式直播期间每帧含一次 store 写入 + React 提交，预算 <8ms；
 * - 会话切换   ：selectSession 乐观切换 → 首个稳定绘制，预算 <50ms（warm/cold 各测）；
 * - 滚动帧     ：脚本化滚动全程无 >16ms 帧。
 *
 * 全部测量在页面内完成：rAF 帧距采样 + PerformanceObserver(longtask) +
 * React Profiler 提交耗时（见 benchProfiler.ts）。不改任何生产路径。
 */

import type {ChatMessage} from '@/lib/types';
import {patchSessionStream} from '@/lib/sessionStreams';
import {setStreamingTextSignal} from '@/lib/streamSignal';
import {useChatStore} from '@/stores/chatStore';
import {replaceMessages} from '@/lib/db';
import {
	drainBenchCommits,
	setBenchPhase,
	startBenchCommits,
	stopBenchCommits,
} from './benchProfiler';

// ---------------------------------------------------------------------------
// 类型
// ---------------------------------------------------------------------------

export type DistStats = {
	n: number;
	mean: number;
	p50: number;
	p95: number;
	max: number;
};

export type LongTaskSummary = {
	count: number;
	totalMs: number;
	maxMs: number;
};

export type TokenBenchResult = {
	/** 每帧总时长（rAF 距），token 帧预算 <8ms 是针对其中的 JS 工作量。 */
	frameDelta: DistStats;
	/** React 提交耗时（Profiler actualDuration）。 */
	commit: DistStats;
	/** 基准驱动循环自身的 JS 开销（不含 React 渲染与绘制）。 */
	driveJs: DistStats;
	over8ms: number;
	over16ms: number;
	longTasks: LongTaskSummary;
	/** 流文本耗尽后从零重启的次数（0 = 全程单调追加）。 */
	restarts: number;
	charsPerFrame: number;
	streamChars: number;
};

export type SettleBenchResult = {
	/** finish()（全文落盘 + 清流）到下一次稳定绘制的耗时。 */
	settleMs: number;
	commit: DistStats;
};

export type SwitchSampleSet = {
	paint: DistStats;
	loaded: DistStats;
	commit: DistStats;
	samples: number;
};

export type SwitchBenchResult = {
	warm: SwitchSampleSet;
	cold: SwitchSampleSet | null;
	/** cold 会话消息条数（IDB 播种规模）。 */
	coldSessionMessages: number;
};

export type ScrollBenchResult = {
	up: ScrollPassResult;
	down: ScrollPassResult;
	jumpToBottom: {frameDelta: DistStats; commit: DistStats} | null;
	rounds: number;
};

export type ScrollPassResult = {
	frames: number;
	frameDelta: DistStats;
	over16: number;
	over32: number;
	commit: DistStats;
	longTasks: LongTaskSummary;
};

export type BudgetCheck = {
	name: string;
	budget: string;
	value: number;
	pass: boolean;
};

export type BenchReport = {
	meta: {
		userAgent: string;
		devicePixelRatio: number;
		viewport: {w: number; h: number};
		roundsPerSession: number;
		sessionCount: number;
		streamChars: number;
		timestamp: string;
	};
	token: TokenBenchResult;
	settle: SettleBenchResult;
	switch: SwitchBenchResult;
	scroll: ScrollBenchResult;
	budgets: BudgetCheck[];
};

export type BenchHarnessContext = {
	/** 主会话（warm，messagesById 已预置）。 */
	sessionId: string;
	/** 次会话 id（null 时 switch 基准跳过）。 */
	secondarySessionId: string | null;
	/** 次会话消息（用于 IDB 播种，cold 切换读它）。 */
	secondaryMessages: ChatMessage[] | null;
	/** 主会话消息条数（供报告 meta）。 */
	primaryMessageCount: number;
	/** 流式回复全文。 */
	streamText: string;
	/** 复位到 settled 初始态（复用 __XY_REPLAY__.reset）。 */
	reset: () => void;
	/** 结束直播并把全文落盘（复用 __XY_REPLAY__.finish）。 */
	finish: () => void;
	/** 按新轮数重建 fixtures 并重装（null 时 synth 不可用）。 */
	reinstall: ((rounds: number, seed?: number) => void) | null;
};

export type BenchApi = {
	runTokenBench: (opts?: {seconds?: number; charsPerFrame?: number}) => Promise<TokenBenchResult & {settle: SettleBenchResult}>;
	runSwitchBench: (opts?: {
		pairs?: number;
		coldTimeoutMs?: number;
	}) => Promise<SwitchBenchResult>;
	runScrollBench: (opts?: {seconds?: number; stepPx?: number}) => Promise<ScrollBenchResult>;
	runAll: () => Promise<BenchReport>;
	report: () => BenchReport | null;
	download: () => void;
	/** 换一轮数重装合成会话（runAll 会自动重跑）。 */
	synth: (rounds: number, seed?: number) => void;
	/**
	 * 顺序扫描多个尺寸：每个尺寸重装 → runAll → 自动下载 JSON。
	 * `?auto=1` 模式与一键脚本用；浏览器首次会询问「允许多个下载」。
	 */
	sweep: (sizes?: number[]) => Promise<BenchReport[]>;
};

declare global {
	interface Window {
		__XY_BENCH__?: BenchApi;
	}
}

// ---------------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------------

const raf = (): Promise<number> =>
	new Promise(resolve => requestAnimationFrame(resolve));

const nextPaint = async (): Promise<void> => {
	await raf();
	await raf();
};

const sleep = (ms: number): Promise<void> =>
	new Promise(resolve => window.setTimeout(resolve, ms));

function stats(values: number[]): DistStats {
	if (values.length === 0) {
		return {n: 0, mean: 0, p50: 0, p95: 0, max: 0};
	}
	const sorted = [...values].sort((a, b) => a - b);
	const at = (q: number): number =>
		sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]!;
	const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length;
	return {n: sorted.length, mean, p50: at(0.5), p95: at(0.95), max: sorted[sorted.length - 1]!};
}

/** rAF 距采样器。 */
class FrameRecorder {
	private samples: number[] = [];
	private last = 0;
	private rafId = 0;
	private running = false;

	start(): void {
		if (this.running) {
			return;
		}
		this.running = true;
		this.samples = [];
		this.last = performance.now();
		const tick = (t: number) => {
			if (!this.running) {
				return;
			}
			this.samples.push(t - this.last);
			this.last = t;
			this.rafId = requestAnimationFrame(tick);
		};
		this.rafId = requestAnimationFrame(tick);
	}

	stop(): number[] {
		this.running = false;
		cancelAnimationFrame(this.rafId);
		return this.samples;
	}
}

/** longtask 采集器（>50ms 阻塞）。 */
class LongTaskCollector {
	private entries: PerformanceEntry[] = [];
	private obs: PerformanceObserver | null = null;

	start(): void {
		if (typeof PerformanceObserver === 'undefined') {
			return;
		}
		try {
			this.obs = new PerformanceObserver(list => {
				this.entries.push(...list.getEntries());
			});
			this.obs.observe({type: 'longtask', buffered: false} as PerformanceObserverInit);
		} catch {
			this.obs = null;
		}
	}

	stop(): LongTaskSummary {
		try {
			this.obs?.disconnect();
		} catch {
			/* noop */
		}
		this.obs = null;
		const durations = this.entries.map(e => e.duration);
		return {
			count: durations.length,
			totalMs: Math.round(durations.reduce((a, b) => a + b, 0)),
			maxMs: durations.length ? Math.round(Math.max(...durations)) : 0,
		};
	}
}

async function until(
	cond: () => boolean,
	timeoutMs = 8000,
): Promise<boolean> {
	const deadline = performance.now() + timeoutMs;
	while (performance.now() < deadline) {
		if (cond()) {
			return true;
		}
		await raf();
	}
	return cond();
}

function commitStats(commits: {actualDuration: number}[]): DistStats {
	return stats(commits.map(c => c.actualDuration));
}

// ---------------------------------------------------------------------------
// 模块状态
// ---------------------------------------------------------------------------

let ctx: BenchHarnessContext | null = null;
let lastReport: BenchReport | null = null;

function requireCtx(): BenchHarnessContext {
	if (!ctx) {
		throw new Error(
			'[xy-bench] harness 未安装：请通过 /bench/chat?rounds=N&bench=1 打开',
		);
	}
	return ctx;
}

/** 与 OfflineReplayRoute.flushStream 相同语义的流式写入。 */
function pushStream(sessionId: string, text: string, status: string): void {
	setStreamingTextSignal(text);
	useChatStore.setState(s => ({
		sessionStreams: patchSessionStream(s.sessionStreams, sessionId, {
			streamingText: text,
			streamingShown: text,
			isLoading: true,
			statusText: status,
		}),
	}));
}

function getScroller(): HTMLElement {
	const el = document.querySelector<HTMLElement>('.xy-hover-scroll');
	if (!el) {
		throw new Error('[xy-bench] 未找到消息滚动容器（.xy-hover-scroll）');
	}
	return el;
}

async function settleAfterReset(): Promise<void> {
	await nextPaint();
	await sleep(300);
	await nextPaint();
}

// ---------------------------------------------------------------------------
// token 基准
// ---------------------------------------------------------------------------

async function runTokenBench(
	opts: {seconds?: number; charsPerFrame?: number} = {},
): Promise<TokenBenchResult & {settle: SettleBenchResult}> {
	const harness = requireCtx();
	const seconds = opts.seconds ?? 6;
	const charsPerFrame = Math.max(1, opts.charsPerFrame ?? 6);
	const {sessionId, streamText} = harness;

	harness.reset();
	await settleAfterReset();

	const warmRec = new FrameRecorder();
	setBenchPhase('token-warmup');
	warmRec.start();
	{
		const warmDeadline = performance.now() + 1000;
		let warmShown = '';
		while (performance.now() < warmDeadline) {
			warmShown = streamText.slice(0, Math.min(streamText.length, warmShown.length + charsPerFrame));
			pushStream(sessionId, warmShown, '本地离线回放');
			await raf();
		}
	}
	warmRec.stop();

	// 复位到 settled 再进入正式测量。
	harness.reset();
	await settleAfterReset();

	const rec = new FrameRecorder();
	const lt = new LongTaskCollector();
	rec.start();
	lt.start();
	startBenchCommits();
	setBenchPhase('token');

	const driveJs: number[] = [];
	const frames: number[] = [];
	const commitsAll: {actualDuration: number}[] = [];
	let shown = 0;
	let restarts = 0;
	const deadline = performance.now() + seconds * 1000;
	let lastFrame = performance.now();

	while (performance.now() < deadline) {
		const t0 = performance.now();
		if (shown >= streamText.length) {
			// 流文本耗尽：清流后从零重播（转录不增长，等价一次新回复）。
			restarts += 1;
			shown = 0;
			pushStream(sessionId, '', '');
		} else {
			shown = Math.min(streamText.length, shown + charsPerFrame);
			pushStream(sessionId, streamText.slice(0, shown), '本地离线回放');
		}
		driveJs.push(performance.now() - t0);
		const t = await raf();
		frames.push(t - lastFrame);
		lastFrame = t;
	}

	commitsAll.push(...drainBenchCommits());
	stopBenchCommits();

	// settle：finish() 落盘全文。
	setBenchPhase('settle');
	startBenchCommits();
	const settleStart = performance.now();
	harness.finish();
	await nextPaint();
	const settleMs = performance.now() - settleStart;
	const settleCommits = drainBenchCommits();
	stopBenchCommits();
	await sleep(300);

	const deltas = rec.stop();
	const longTasks = lt.stop();
	setBenchPhase('idle');

	const result: TokenBenchResult & {settle: SettleBenchResult} = {
		frameDelta: stats(frames.length ? frames : deltas),
		commit: commitStats(commitsAll),
		driveJs: stats(driveJs),
		over8ms: frames.filter(d => d > 8).length,
		over16ms: frames.filter(d => d > 16).length,
		longTasks,
		restarts,
		charsPerFrame,
		streamChars: streamText.length,
		settle: {
			settleMs: Math.round(settleMs * 100) / 100,
			commit: commitStats(settleCommits),
		},
	};
	return result;
}

// ---------------------------------------------------------------------------
// 会话切换基准
// ---------------------------------------------------------------------------

function evictMessages(sessionId: string): void {
	useChatStore.setState(s => {
		if (s.messagesById[sessionId] === undefined) {
			return s;
		}
		const messagesById = {...s.messagesById};
		delete messagesById[sessionId];
		return {messagesById};
	});
}

async function measureSwitch(
	targetId: string,
	label: string,
	loadedTimeoutMs = 8000,
): Promise<{paint: number[]; loaded: number[]; commits: {actualDuration: number}[]}> {
	const t0 = performance.now();
	void useChatStore.getState().selectSession(targetId);
	await nextPaint();
	const paintMs = performance.now() - t0;
	const loadedOk = await until(() => {
		const st = useChatStore.getState();
		return (
			st.messagesById[targetId] !== undefined &&
			!st.messagesLoadingIds[targetId]
		);
	}, loadedTimeoutMs);
	const loadedMs = performance.now() - t0;
	if (!loadedOk) {
		console.warn(`[xy-bench] switch ${label} 未在超时内完成装载`);
	}
	await sleep(120);
	return {
		paint: [paintMs],
		loaded: [loadedMs],
		commits: drainBenchCommits(),
	};
}

async function runSwitchBench(
	opts: {pairs?: number; coldTimeoutMs?: number} = {},
): Promise<SwitchBenchResult> {
	const harness = requireCtx();
	const pairs = Math.max(1, opts.pairs ?? 4);
	const coldTimeoutMs = opts.coldTimeoutMs ?? 8000;
	const {sessionId, secondarySessionId} = harness;
	if (!secondarySessionId) {
		throw new Error('[xy-bench] switch 基准需要次会话（重开页面即可）');
	}
	const secondaryId = secondarySessionId;

	harness.reset();
	await settleAfterReset();

	const warmPaint: number[] = [];
	const warmLoaded: number[] = [];
	const warmCommits: {actualDuration: number}[] = [];

	for (let i = 0; i < pairs; i += 1) {
		setBenchPhase('switch-warm');
		startBenchCommits();
		const toB = await measureSwitch(secondaryId, 'warm→B', coldTimeoutMs);
		warmPaint.push(...toB.paint);
		warmLoaded.push(...toB.loaded);
		warmCommits.push(...toB.commits);
		const toA = await measureSwitch(sessionId, 'warm→A', coldTimeoutMs);
		warmPaint.push(...toA.paint);
		warmLoaded.push(...toA.loaded);
		warmCommits.push(...toA.commits);
		stopBenchCommits();
	}

	// cold：B 已在 install 时播种 IDB；从 store 摘除后走真实冷装载管线。
	let coldSet: SwitchSampleSet | null = null;
	if (harness.secondaryMessages) {
		const coldPaint: number[] = [];
		const coldLoaded: number[] = [];
		const coldCommits: {actualDuration: number}[] = [];
		const coldPasses = Math.min(3, pairs);
		for (let i = 0; i < coldPasses; i += 1) {
			// 回到 A 并等待完全就绪。
			await measureSwitch(sessionId, 'cold-pre→A', coldTimeoutMs);
			await until(
				() => !useChatStore.getState().messagesLoadingIds[secondaryId],
				coldTimeoutMs,
			);
			setBenchPhase('switch-cold');
			startBenchCommits();
			// 同步块内 evict + selectSession：中间不产生绘制。
			evictMessages(secondaryId);
			const r = await measureSwitch(secondaryId, 'cold→B', coldTimeoutMs);
			coldPaint.push(...r.paint);
			coldLoaded.push(...r.loaded);
			coldCommits.push(...r.commits);
			stopBenchCommits();
		}
		coldSet = {
			paint: stats(coldPaint),
			loaded: stats(coldLoaded),
			commit: commitStats(coldCommits),
			samples: coldPaint.length,
		};
	}

	setBenchPhase('idle');
	return {
		warm: {
			paint: stats(warmPaint),
			loaded: stats(warmLoaded),
			commit: commitStats(warmCommits),
			samples: warmPaint.length,
		},
		cold: coldSet,
		coldSessionMessages: harness.secondaryMessages?.length ?? 0,
	};
}

// ---------------------------------------------------------------------------
// 滚动基准
// ---------------------------------------------------------------------------

async function scrollPass(
	scroller: HTMLElement,
	direction: 'up' | 'down',
	stepPx: number,
	seconds: number,
): Promise<ScrollPassResult> {
	const rec = new FrameRecorder();
	const lt = new LongTaskCollector();
	startBenchCommits();
	setBenchPhase(direction === 'up' ? 'scroll-up' : 'scroll-down');
	rec.start();
	lt.start();

	const deadline = performance.now() + seconds * 1000;
	let lastFrame = performance.now();
	const frameDeltas: number[] = [];
	scroller.scrollTop =
		direction === 'up' ? scroller.scrollHeight : 0;
	await nextPaint();

	for (;;) {
		const t = await raf();
		frameDeltas.push(t - lastFrame);
		lastFrame = t;
		const max = scroller.scrollHeight - scroller.clientHeight;
		if (direction === 'up') {
			scroller.scrollTop = Math.max(0, scroller.scrollTop - stepPx);
			if (scroller.scrollTop <= 0) {
				break;
			}
		} else {
			scroller.scrollTop = Math.min(max, scroller.scrollTop + stepPx);
			if (scroller.scrollTop >= max) {
				break;
			}
		}
		if (t > deadline) {
			break;
		}
	}
	await nextPaint();

	const commits = drainBenchCommits();
	stopBenchCommits();
	const deltas = rec.stop();
	const longTasks = lt.stop();
	return {
		frames: deltas.length,
		frameDelta: stats(deltas),
		over16: deltas.filter(d => d > 16).length,
		over32: deltas.filter(d => d > 32).length,
		commit: commitStats(commits),
		longTasks,
	};
}

async function runScrollBench(
	opts: {seconds?: number; stepPx?: number} = {},
): Promise<ScrollBenchResult> {
	const harness = requireCtx();
	const seconds = opts.seconds ?? 5;
	const stepPx = opts.stepPx ?? 900;

	harness.reset();
	await settleAfterReset();

	const scroller = getScroller();
	// 先落到底部（自然落位），再向上滚全程。
	scroller.scrollTop = scroller.scrollHeight;
	await nextPaint();
	await sleep(200);

	const up = await scrollPass(scroller, 'up', stepPx, seconds);
	const down = await scrollPass(scroller, 'down', stepPx, seconds);

	// 跳底（TurnRail jump / 落位的极端情形）。
	setBenchPhase('scroll-jump');
	startBenchCommits();
	scroller.scrollTop = 0;
	await nextPaint();
	const jumpStart = performance.now();
	scroller.scrollTop = scroller.scrollHeight;
	await nextPaint();
	const jumpFrames: number[] = [performance.now() - jumpStart];
	const j1 = await raf();
	jumpFrames.push(j1 - jumpStart);
	const jumpCommits = drainBenchCommits();
	stopBenchCommits();
	setBenchPhase('idle');

	return {
		up,
		down,
		jumpToBottom: {
			frameDelta: stats(jumpFrames),
			commit: commitStats(jumpCommits),
		},
		rounds: harness.primaryMessageCount,
	};
}

// ---------------------------------------------------------------------------
// 汇总
// ---------------------------------------------------------------------------

function evaluateBudgets(report: Omit<BenchReport, 'budgets'>): BudgetCheck[] {
	const tokenP95 = report.token.commit.n > 0 ? report.token.commit.p95 : report.token.frameDelta.p95;
	return [
		{
			name: 'token 帧 React 提交 p95',
			budget: '< 8ms',
			value: Math.round(tokenP95 * 100) / 100,
			pass: tokenP95 < 8,
		},
		{
			name: '会话切换（warm）paint p95',
			budget: '< 50ms',
			value: Math.round(report.switch.warm.paint.p95 * 100) / 100,
			pass: report.switch.warm.paint.p95 < 50,
		},
		{
			name: '会话切换（cold）paint p95',
			budget: '< 50ms（目标值待确认）',
			value: report.switch.cold
				? Math.round(report.switch.cold.paint.p95 * 100) / 100
				: Number.NaN,
			pass: Boolean(report.switch.cold && report.switch.cold.paint.p95 < 50),
		},
		{
			name: '滚动 >16ms 帧数（up+down）',
			budget: '0',
			value: report.scroll.up.over16 + report.scroll.down.over16,
			pass: report.scroll.up.over16 + report.scroll.down.over16 === 0,
		},
	];
}

function printSummary(report: BenchReport): void {
	console.groupCollapsed('[xy-bench] 基线报告摘要');
	console.table(
		report.budgets.map(b => ({
			指标: b.name,
			预算: b.budget,
			实测: b.value,
			结论: b.pass ? 'PASS' : 'FAIL',
		})),
	);
	console.table({
		token帧: {
			帧距p50: report.token.frameDelta.p50,
			帧距p95: report.token.frameDelta.p95,
			提交p95: report.token.commit.p95,
			'>8ms': report.token.over8ms,
			'>16ms': report.token.over16ms,
		},
		会话切换warm: {
			paintP50: report.switch.warm.paint.p50,
			paintP95: report.switch.warm.paint.p95,
			loadedP95: report.switch.warm.loaded.p95,
		},
		滚动up: {
			帧数: report.scroll.up.frames,
			'>16ms': report.scroll.up.over16,
			帧距p95: report.scroll.up.frameDelta.p95,
			帧距max: report.scroll.up.frameDelta.max,
		},
	});
	console.groupEnd();
}

async function runAll(): Promise<BenchReport> {
	const harness = requireCtx();
	const token = await runTokenBench();
	const switchResult = await runSwitchBench();
	const scroll = await runScrollBench();

	const report: BenchReport = {
		meta: {
			userAgent: navigator.userAgent,
			devicePixelRatio: window.devicePixelRatio,
			viewport: {w: window.innerWidth, h: window.innerHeight},
			// 消息条数（文件名 r<此值>）。轮数 ≈ messages/2.36（合成转录形态）。
			roundsPerSession: harness.primaryMessageCount,
			sessionCount: harness.secondarySessionId ? 2 : 1,
			streamChars: harness.streamText.length,
			timestamp: new Date().toISOString(),
		},
		token,
		settle: token.settle,
		switch: switchResult,
		scroll,
		budgets: [],
	};
	report.budgets = evaluateBudgets(report);
	lastReport = report;
	printSummary(report);
	return report;
}

function download(): void {
	const report = lastReport;
	if (!report) {
		console.warn('[xy-bench] 尚无报告：先执行 await __XY_BENCH__.runAll()');
		return;
	}
	const blob = new Blob([JSON.stringify(report, null, 2)], {
		type: 'application/json',
	});
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = `xy-bench-r${report.meta.roundsPerSession}-${new Date()
		.toISOString()
		.replace(/[:.]/g, '-')}.json`;
	a.click();
	URL.revokeObjectURL(url);
}

/**
 * 尺寸扫描：每个尺寸重装 → 稳定 → runAll → 下载。
 * 供 `?auto=1`（一键脚本）与手动 `__XY_BENCH__.sweep()` 使用。
 */
async function runSweep(
	sizes: number[] = [5000, 2000, 500],
): Promise<BenchReport[]> {
	const harness = requireCtx();
	if (!harness.reinstall) {
		throw new Error('[xy-bench] sweep 需要 synthetic 模式（?rounds=…）');
	}
	console.info(
		`[xy-bench] sweep 开始：${sizes.join(' → ')}。首次下载前浏览器会询问「允许下载多个文件」，请允许。`,
	);
	const reports: BenchReport[] = [];
	for (const rounds of sizes) {
		console.info(`[xy-bench] sweep：重装 rounds=${rounds} …`);
		harness.reinstall(rounds);
		await sleep(1200);
		const report = await runAll();
		reports.push(report);
		try {
			download();
		} catch (err) {
			console.warn('[xy-bench] 自动下载失败（不影响报告内容，可手动 __XY_BENCH__.download()）', err);
		}
	}
	console.info(
		`[xy-bench] sweep 完成：${reports.length} 份 JSON 已下载（rounds=${reports.map(r => r.meta.roundsPerSession).join('/')}）。`,
	);
	return reports;
}

// ---------------------------------------------------------------------------
// 安装
// ---------------------------------------------------------------------------

export function installBenchHarness(context: BenchHarnessContext): void {
	ctx = context;
	// cold 基准的 IDB 播种：失败只影响 cold 采样（until 超时会告警）。
	if (context.secondarySessionId && context.secondaryMessages) {
		void replaceMessages(context.secondarySessionId, context.secondaryMessages).catch(
			err => console.warn('[xy-bench] IDB 播种失败', err),
		);
	}
	const api: BenchApi = {
		runTokenBench,
		runSwitchBench,
		runScrollBench,
		runAll,
		report: () => lastReport,
		download,
		synth: (rounds, seed) => {
			if (!ctx?.reinstall) {
				throw new Error('[xy-bench] reinstall 不可用');
			}
			lastReport = null;
			ctx.reinstall(rounds, seed);
		},
		sweep: runSweep,
	};
	window.__XY_BENCH__ = api;
	console.info(
		'[xy-bench] 已安装。`await __XY_BENCH__.runAll()` 采集当前尺寸；`__XY_BENCH__.sweep([5000,2000,500])` 自动扫描并下载各尺寸 JSON。',
	);
}
