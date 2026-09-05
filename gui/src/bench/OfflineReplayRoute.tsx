import {Profiler, useEffect, useState} from 'react';
import type {ChatMessage, ChatSession, ChatSpace} from '@/lib/types';
import {ChatPage} from '@/pages/ChatPage';
import {setStreamingTextSignal} from '@/lib/streamSignal';
import {patchSessionStream} from '@/lib/sessionStreams';
import {useChatStore} from '@/stores/chatStore';
import {installBenchHarness, type BenchHarnessContext} from './benchHarness';
import {onBenchProfilerRender} from './benchProfiler';
import {
	buildSyntheticMessages,
	buildSyntheticStreamReply,
} from './syntheticTranscript';

type ReplayFixture = {
	version: number;
	sessionId: string;
	spaceId: string;
	scenario: string;
	messages: ChatMessage[];
	streamText: string;
};

/** switch 基准用的次会话（warm 预置进 store，cold 播种 IDB）。 */
type ReplayExtra = {
	session: ChatSession;
	messages: ChatMessage[];
};

type ReplayApi = {
	sessionId: string;
	streamText: string;
	reset: () => void;
	setStream: (text: string, status?: string) => void;
	finish: () => void;
	setSidebarOpen: (open: boolean) => void;
};

declare global {
	interface Window {
		__XY_REPLAY__?: ReplayApi;
	}
}

const BENCH_SESSION_ID = 'xy-offline-replay';
const BENCH_SESSION_B_ID = 'xy-offline-replay-b';
const BENCH_SPACE_ID = 'xy-offline-space';
const BENCH_DEFAULT_SEED = 20240501;

function makeSession(fixture: ReplayFixture): ChatSession {
	const now = Date.now();
	return {
		id: fixture.sessionId,
		spaceId: fixture.spaceId,
		title: '离线性能回放',
		createdAt: now,
		updatedAt: now,
	};
}

function makeSpace(fixture: ReplayFixture): ChatSpace {
	const now = Date.now();
	return {
		id: fixture.spaceId,
		name: 'Offline Replay',
		rootPath: '',
		createdAt: now,
		updatedAt: now,
	};
}

function installReplay(fixture: ReplayFixture, extras: ReplayExtra[] = []) {
	const session = makeSession(fixture);
	const space = makeSpace(fixture);
	const initialMessages = fixture.messages;
	let finished = false;
	let streamRaf = 0;
	let queuedStreamText = '';
	let queuedStatus = '';

	const flushStream = () => {
		streamRaf = 0;
		if (finished) {
			return;
		}
		const text = queuedStreamText;
		const status = queuedStatus;
		setStreamingTextSignal(text);
			useChatStore.setState(s => ({
			sessionStreams: patchSessionStream(s.sessionStreams, fixture.sessionId, {
				streamingText: text,
				streamingShown: text,
				isLoading: true,
				statusText: status,
			}),
		}));
	};

	const reset = () => {
		if (streamRaf) {
			cancelAnimationFrame(streamRaf);
			streamRaf = 0;
		}
		queuedStreamText = '';
		queuedStatus = '';
			finished = false;
			setStreamingTextSignal('');
			useChatStore.setState({
			hydrated: true,
			spaces: [space],
			sessions: [session, ...extras.map(e => e.session)],
			activeId: fixture.sessionId,
			activeSpaceId: fixture.spaceId,
			messagesById: {
				[fixture.sessionId]: initialMessages,
				...Object.fromEntries(extras.map(e => [e.session.id, e.messages])),
			},
			// JSON 回放路径恒为空对象（hydrate 被跳过）；synth 重装时清掉
			// 上一次会话可能残留的在途装载标记。
			messagesLoadingIds: {},
			sessionStreams: {},
			errorBanner: null,
			errorBannerSessionId: null,
			sessionTodosById: {[fixture.sessionId]: null},
			sessionGoalById: {[fixture.sessionId]: null},
			sessionJobsById: {},
			sessionUsageById: {[fixture.sessionId]: null},
		});
	};

	reset();
	window.__XY_REPLAY__ = {
		sessionId: fixture.sessionId,
		streamText: fixture.streamText,
		reset,
			setStream(text, status = '本地离线回放') {
				finished = false;
				queuedStreamText = text;
				queuedStatus = status;
				if (!streamRaf) {
					streamRaf = requestAnimationFrame(flushStream);
				}
			},
			finish() {
				if (streamRaf) {
					cancelAnimationFrame(streamRaf);
					streamRaf = 0;
				}
				if (finished) {
				return;
			}
			finished = true;
				setStreamingTextSignal('');
				useChatStore.setState(s => ({
				messagesById: {
					...s.messagesById,
					[fixture.sessionId]: [
						...(s.messagesById[fixture.sessionId] ?? []),
						{
							id: 'replay-stream-final',
							role: 'assistant',
							text: fixture.streamText,
							createdAt: Date.now(),
						},
					],
				},
				sessionStreams: {},
			}));
		},
		setSidebarOpen(open) {
			useChatStore.getState().setSidebarOpen(open);
		},
	};
}

function parseBenchQuery(): {rounds: number; seed: number; auto: boolean} {
	if (typeof window === 'undefined') {
		return {rounds: 0, seed: BENCH_DEFAULT_SEED, auto: false};
	}
	const params = new URLSearchParams(window.location.search);
	const rounds = Math.max(0, Math.floor(Number(params.get('rounds') ?? '0')) || 0);
	const seedRaw = Number(params.get('seed') ?? '0');
	return {
		rounds,
		seed: Number.isFinite(seedRaw) && seedRaw > 0 ? seedRaw : BENCH_DEFAULT_SEED,
		auto: rounds > 0 && params.get('auto') === '1',
	};
}

/** auto 模式的默认扫描尺寸（从大到小；首个为 URL rounds 的兜底口径）。 */
const AUTO_SWEEP_SIZES = [5000, 2000, 500];

export function OfflineReplayRoute() {
	const [ready, setReady] = useState(false);
	// 合成基准模式：/bench/chat?rounds=N —— 只在该模式下挂 Profiler 与
	// __XY_BENCH__；默认 JSON 回放路径行为与原来完全一致。
	const [bench] = useState(() => parseBenchQuery());

	useEffect(() => {
		if (bench.rounds > 0) {
			const streamText = buildSyntheticStreamReply(bench.seed + 77);
			const buildFixture = (rounds: number, seed: number): ReplayFixture => ({
				version: 1,
				sessionId: BENCH_SESSION_ID,
				spaceId: BENCH_SPACE_ID,
				scenario: 'synthetic-bench',
				messages: buildSyntheticMessages({rounds, seed}),
				streamText,
			});
			const makeSecondary = (rounds: number, seed: number): ReplayExtra => {
				const now = Date.now();
				return {
					session: {
						id: BENCH_SESSION_B_ID,
						spaceId: BENCH_SPACE_ID,
						title: '离线回放 B',
						createdAt: now,
						updatedAt: now,
					},
					messages: buildSyntheticMessages({rounds, seed}),
				};
			};

			const installWith = (rounds: number, seed: number) => {
				const fixture = buildFixture(rounds, seed);
				const secondary = makeSecondary(rounds, seed + 1);
				installReplay(fixture, [secondary]);
				const harnessCtx: BenchHarnessContext = {
					sessionId: fixture.sessionId,
					secondarySessionId: secondary.session.id,
					secondaryMessages: secondary.messages,
					primaryMessageCount: fixture.messages.length,
					streamText: fixture.streamText,
					reset: () => window.__XY_REPLAY__?.reset(),
					finish: () => window.__XY_REPLAY__?.finish(),
					reinstall: (nextRounds, nextSeed) =>
						installWith(nextRounds, nextSeed ?? bench.seed),
				};
				installBenchHarness(harnessCtx);
			};

			installWith(bench.rounds, bench.seed);

			// 一键脚本 / ?auto=1：页面就绪后自动顺序扫描三个尺寸并下载 JSON。
			let autoTimer: number | undefined;
			if (bench.auto) {
				autoTimer = window.setTimeout(() => {
					void window.__XY_BENCH__
						?.sweep(AUTO_SWEEP_SIZES)
						.catch(err => console.error('[xy-bench] 自动 sweep 失败', err));
				}, 2500);
			}

			setReady(true);
			return () => {
				if (autoTimer !== undefined) {
					window.clearTimeout(autoTimer);
				}
				delete window.__XY_REPLAY__;
				delete window.__XY_BENCH__;
			};
		}

		let cancelled = false;
		void fetch('/bench/chat-replay.json', {cache: 'no-store'})
			.then(response => {
				if (!response.ok) {
					throw new Error(`replay fixture HTTP ${response.status}`);
				}
				return response.json() as Promise<ReplayFixture>;
			})
			.then(fixture => {
				if (cancelled) {
					return;
				}
				installReplay(fixture);
				setReady(true);
			})
			.catch(error => {
				if (!cancelled) {
					console.error('[xy-replay] fixture load failed', error);
				}
			});
		return () => {
			cancelled = true;
			delete window.__XY_REPLAY__;
		};
	}, [bench]);

	if (!ready) {
		return (
			<div className="flex h-full w-full items-center justify-center bg-paper text-sm text-mute">
				正在载入离线性能回放…
			</div>
		);
	}

	if (bench.rounds > 0) {
		return (
			<Profiler id="xy-bench-chatpage" onRender={onBenchProfilerRender}>
				<ChatPage />
			</Profiler>
		);
	}

	return <ChatPage />;
}
