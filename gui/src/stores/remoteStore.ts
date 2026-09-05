import {create} from 'zustand';
import {sessionErrorBannerPatch} from '@/lib/pendingForSession';
import {
	filehelperQrUrl,
	filehelperStart,
	filehelperStatus,
	filehelperStop,
	ilinkQrUrl,
	ilinkStart,
	ilinkStatus,
	ilinkStop,
	type FileHelperStatus,
} from '@/lib/api';
import {assembleStream} from '@/lib/remoteStream';
import {allowsEmptyApiKey} from '@/lib/localTestGate';
import {
	gateRemotePayload,
	getRemoteMirrorSession,
	resetRemoteMirrorSession,
	type RemotePayloadKind,
} from '@/lib/remoteSession';
import {hasRemoteStreaming} from '@/lib/sessionStreams';
import {useChatStore} from '@/stores/chatStore';
import {useSettingsStore, type RemoteChannel} from '@/stores/settingsStore';

type RemoteUiState = {
	state: FileHelperStatus['state'];
	loggedIn: boolean;
	hasQr: boolean;
	error: string | null;
	hint: string | null;
	qrRev: number;
	busy: boolean;
	panelOpen: boolean;
	lastEventId: string;
	streaming: boolean;
	sseConnected: boolean;
	pollError: string | null;
	startRemote: () => Promise<void>;
	stopRemote: () => Promise<void>;
	toggleRemote: () => Promise<void>;
	pollRemote: (opts?: {heartbeat?: boolean}) => Promise<void>;
	hydrateRemote: () => Promise<void>;
	handleSsePayload: (kind: string, data: Record<string, unknown>) => void;
	setSseConnected: (connected: boolean) => void;
	setPanelOpen: (open: boolean) => void;
};

let pollInFlight = false;
let pollEpoch = 0;
let streamAcc = '';
let streamFrom = 0;
const seenEventIds = new Set<string>();
const seenToolIds = new Set<string>();

function addCapped(target: Set<string>, id: string, cap = 5000) {
	target.add(id);
	if (target.size > cap) {
		const oldest = target.values().next().value;
		if (oldest !== undefined) {
			target.delete(oldest);
		}
	}
}

let pendingStream: {text: string; status: string} | null = null;
let streamRaf = 0;

function currentChannel(): RemoteChannel {
	return useSettingsStore.getState().remoteChannel === 'ilink'
		? 'ilink'
		: 'filehelper';
}

function channelApi() {
	if (currentChannel() === 'ilink') {
		return {start: ilinkStart, stop: ilinkStop, status: ilinkStatus};
	}
	return {
		start: filehelperStart,
		stop: filehelperStop,
		status: filehelperStatus,
	};
}

export function remoteQrUrl(rev = 0): string {
	return currentChannel() === 'ilink' ? ilinkQrUrl(rev) : filehelperQrUrl(rev);
}

function applyRemoteTools(tools: FileHelperStatus['stream_tools']) {
	if (!tools?.length) {
		return;
	}
	flushStreamRaf();
	const chat = useChatStore.getState();
	for (const rec of tools) {
		if (!rec?.name) {
			continue;
		}
		if (!gateRemotePayload('tool', rec as Record<string, unknown>)) {
			continue;
		}
		if (rec.id && seenToolIds.has(rec.id)) {
			continue;
		}
		if (rec.id) {
			addCapped(seenToolIds, rec.id);
		}
		if (rec.kind === 'tool_call') {
			chat.applyRemoteToolCall(rec.name, rec.input);
		} else if (rec.kind === 'tool_result') {
			chat.applyRemoteToolResult(
				rec.name,
				rec.output ?? '',
				Boolean(rec.is_error),
			);
		}
	}
}

function eventKind(kind: string | undefined): RemotePayloadKind {
	if (kind === 'inbound') {
		return 'inbound';
	}
	if (kind === 'outbound') {
		return 'outbound';
	}
	return 'other';
}

function applyEvents(events: FileHelperStatus['events']) {
	const chat = useChatStore.getState();
	for (const ev of events) {
		if (ev.id && seenEventIds.has(ev.id)) {
			continue;
		}
		if (ev.id) {
			addCapped(seenEventIds, ev.id);
		}
		const prevMirror = getRemoteMirrorSession();
		const gated = gateRemotePayload(eventKind(ev.kind), {
			session_id: ev.session_id ?? '',
		});
		if (
			ev.kind === 'inbound' &&
			prevMirror &&
			getRemoteMirrorSession() !== prevMirror
		) {
			resetStreamAcc();
			applyStreamingFlag(false);
			if (hasRemoteStreaming(useChatStore.getState())) {
				useChatStore.getState().finishRemoteStream();
			}
		}
		if (!gated) {
			continue;
		}
		if (!ev.text?.trim()) {
			continue;
		}
		if (ev.kind === 'error' || ev.kind === 'warn') {
			continue;
		}
		if (ev.kind === 'inbound') {
			const raw = ev.text.replace(/^\s*\[远程\]\s*/, '').trim();
			if (raw.startsWith('[XEYO]') || /(^|\n)\s*\[XEYO\]/.test(raw)) {
				continue;
			}
			const text = ev.text.startsWith('[远程]')
				? ev.text
				: `[远程]\n${ev.text}`;
			chat.appendRemoteMessage('user', text);
		} else if (ev.kind === 'outbound') {
			if (/回复未能发到微信/.test(ev.text)) {
				continue;
			}
			resetStreamAcc();
			chat.commitRemoteStream(ev.text);
		} else if (ev.kind === 'permission') {
			if (!ev.request_id) {
				continue;
			}
			useChatStore.getState().setPendingPermission?.({
					requestId: ev.request_id,
					toolName: ev.tool_name ?? '',
					prompt: ev.text || '',
					reason: ev.reason ?? '',
					sessionId:
						getRemoteMirrorSession() ??
						useChatStore.getState().activeId ??
						'',
			});
		}
	}
}

function flushStreamRaf() {
	if (streamRaf) {
		cancelAnimationFrame(streamRaf);
		streamRaf = 0;
	}
	if (!pendingStream) {
		return;
	}
	const next = pendingStream;
	pendingStream = null;
	useChatStore.getState().syncRemoteStream(next.text, next.status);
}

function scheduleStream(text: string, status: string) {
	pendingStream = {text, status};
	if (streamRaf) {
		return;
	}
	streamRaf = requestAnimationFrame(() => {
		streamRaf = 0;
		flushStreamRaf();
	});
}

function resetStreamAcc() {
	streamAcc = '';
	streamFrom = 0;
	pendingStream = null;
	if (streamRaf) {
		cancelAnimationFrame(streamRaf);
		streamRaf = 0;
	}
}

function applyStreamPayload(st: FileHelperStatus): boolean {
	if (
		!gateRemotePayload('stream', {
			stream_session_id: st.stream_session_id ?? '',
			session_id: st.session_id ?? '',
			last_session_id: st.last_session_id ?? '',
		})
	) {
		return false;
	}
	if (!st.streaming) {
		resetStreamAcc();
		if (hasRemoteStreaming(useChatStore.getState())) {
			useChatStore.getState().finishRemoteStream();
		}
		return true;
	}
	const chunk = st.stream_text ?? '';
	const serverLen =
		typeof st.stream_len === 'number'
			? st.stream_len
			: streamFrom + chunk.length;
	const next = assembleStream({
		acc: streamAcc,
		from: streamFrom,
		chunk,
		serverLen,
		reset: Boolean(st.stream_reset),
	});
	streamAcc = next.acc;
	streamFrom = next.from;
	scheduleStream(streamAcc, st.stream_status ?? '');
	applyRemoteTools(st.stream_tools);
	return true;
}

/** 仅在标志翻转时写 store，避免 TitleBar / QR 面板跟着 token 刷。 */
export function streamingFlagUpdate(
	current: boolean,
	next: boolean,
): {streaming: boolean} | undefined {
	if (current === next) {
		return undefined;
	}
	return {streaming: next};
}

function applyStreamingFlag(next: boolean) {
	const patch = streamingFlagUpdate(useRemoteStore.getState().streaming, next);
	if (patch) {
		useRemoteStore.setState(patch);
	}
}

function applySseDelta(data: Record<string, unknown>) {
	if (!gateRemotePayload('stream', data)) {
		return;
	}
	const streaming = Boolean(data.streaming);
	const fullText = typeof data.text === 'string' ? data.text : '';
	const status = typeof data.status === 'string' ? data.status : '';
	const reset = Boolean(data.reset);
	const serverLen = typeof data.len === 'number' ? data.len : fullText.length;

	if (!streaming) {
		resetStreamAcc();
		if (hasRemoteStreaming(useChatStore.getState())) {
			useChatStore.getState().finishRemoteStream();
		}
		applyStreamingFlag(false);
		return;
	}

	const next = assembleStream({
		acc: streamAcc,
		from: streamFrom,
		chunk: reset ? fullText : fullText.slice(streamFrom),
		serverLen,
		reset,
	});
	streamAcc = next.acc;
	streamFrom = next.from;
	scheduleStream(streamAcc, status);
	applyStreamingFlag(true);
}

export function pollIssueFromStatus(st: {
	last_poll_error?: string | null;
	hint?: string | null;
	error?: string | null;
}): string | null {
	const sendFail = (st.error ?? '').trim();
	if (
		sendFail.includes('回复未能发到微信') ||
		sendFail.includes('连不上微信网关')
	) {
		return sendFail;
	}
	const err = (st.last_poll_error ?? '').trim();
	if (err && err !== 'timeout') {
		return err;
	}
	const hint = (st.hint ?? '').trim();
	if (hint.includes('连不上微信网关')) {
		return hint;
	}
	return null;
}

function applySseState(data: Record<string, unknown>) {
	const st = data as Partial<FileHelperStatus>;
	const events = (st.events as FileHelperStatus['events'] | undefined) ?? [];
	if (events.length) {
		applyEvents(events);
	}
	applyRemoteTools(st.stream_tools);
	let streamApplied = true;
	if (typeof st.streaming === 'boolean') {
		if (st.streaming && typeof st.stream_text === 'string') {
			const full = st.stream_text;
			const len =
				typeof st.stream_len === 'number' ? st.stream_len : full.length;
			if (len === full.length) {
				resetStreamAcc();
				streamApplied = applyStreamPayload({
					...(st as FileHelperStatus),
					stream_reset: true,
				});
			} else {
				streamApplied = applyStreamPayload(st as FileHelperStatus);
			}
		} else if (!st.streaming) {
			streamApplied = applyStreamPayload(st as FileHelperStatus);
		}
	}
	const cur = useRemoteStore.getState();
	const last =
		events.length > 0 ? events[events.length - 1]!.id : cur.lastEventId;
	useRemoteStore.setState({
		state: (st.state as RemoteUiState['state']) ?? cur.state,
		loggedIn:
			typeof st.logged_in === 'boolean' ? st.logged_in : cur.loggedIn,
		hasQr: typeof st.has_qr === 'boolean' ? st.has_qr : cur.hasQr,
		error: (st.error as string | null) ?? null,
		hint: (st.hint as string | null) ?? null,
		qrRev: typeof st.qr_rev === 'number' ? st.qr_rev : cur.qrRev,
		lastEventId: last,
		streaming:
			typeof st.streaming === 'boolean' && streamApplied
				? st.streaming
				: cur.streaming,
		pollError: pollIssueFromStatus({
			last_poll_error: st.last_poll_error,
			hint: (st.hint as string | null) ?? cur.hint,
			error: (st.error as string | null) ?? cur.error,
		}),
	});
}

export const useRemoteStore = create<RemoteUiState>((set, get) => ({
	state: 'stopped',
	loggedIn: false,
	hasQr: false,
	error: null,
	hint: null,
	qrRev: 0,
	busy: false,
	panelOpen: false,
	lastEventId: '',
	streaming: false,
	sseConnected: false,
	pollError: null,
	setPanelOpen(open) {
		set({panelOpen: open});
	},
	setSseConnected(connected) {
		set({sseConnected: connected});
	},
	handleSsePayload(kind, data) {
		if (kind === 'event') {
			const ev = data as FileHelperStatus['events'][number];
			if (ev?.id) {
				set({lastEventId: ev.id});
			}
			applyEvents([ev]);
			return;
		}
		if (kind === 'delta') {
			applySseDelta(data);
			return;
		}
		if (kind === 'tool') {
			if (!gateRemotePayload('tool', data)) {
				return;
			}
			applyRemoteTools([
				data as NonNullable<FileHelperStatus['stream_tools']>[number],
			]);
			return;
		}
		if (kind === 'state') {
			applySseState(data);
		}
	},
	async startRemote() {
		pollEpoch += 1;
		const settings = useSettingsStore.getState();
		// 空 Key 仅允许本地测试 provider（localTestGate，T25c）。
		if (!settings.apiKey.trim() && !allowsEmptyApiKey(settings.provider)) {
			settings.openSettings();
			useChatStore.setState(
				sessionErrorBannerPatch(null, '远程需要 API Key，请先在设置中填写。'),
			);
			return;
		}
		resetStreamAcc();
		seenEventIds.clear();
		seenToolIds.clear();
		resetRemoteMirrorSession();
		set({
			busy: true,
			panelOpen: true,
			error: null,
			hint: null,
			state: 'starting',
			hasQr: false,
			loggedIn: false,
			streaming: false,
			sseConnected: false,
			pollError: null,
		});
		try {
			const st = await channelApi().start({
				// 空 Key 占位仅限本地测试 provider（localTestGate，T25c）。
				api_key: settings.apiKey.trim() || (allowsEmptyApiKey(settings.provider) ? 'local' : ''),
				provider: settings.provider,
				model: settings.model,
				base_url: settings.resolvedBaseUrl(),
			});
			const failed = st.state === 'stopped' || st.state === 'error';
			set({
				state: failed && !st.logged_in ? 'error' : st.state,
				loggedIn: st.logged_in,
				hasQr: st.has_qr,
				error:
					st.error ||
					(failed && !st.logged_in ? '远程未能启动' : null),
				hint: st.hint ?? null,
				qrRev: st.qr_rev ?? 0,
				busy: false,
				panelOpen: st.state !== 'logged_in',
				streaming: Boolean(st.streaming),
				pollError: pollIssueFromStatus(st),
			});
		} catch (err) {
			set({
				busy: false,
				state: 'error',
				error: err instanceof Error ? err.message : String(err),
				panelOpen: true,
			});
		}
	},
	async stopRemote() {
		pollEpoch += 1;
		set({busy: true});
		try {
			await channelApi().stop();
		} catch {
			/* 仍关闭面板 */
		}
		resetStreamAcc();
		seenEventIds.clear();
		seenToolIds.clear();
		useChatStore.getState().finishRemoteStream();
		resetRemoteMirrorSession();
		set({
			state: 'stopped',
			loggedIn: false,
			hasQr: false,
			error: null,
			hint: null,
			busy: false,
			panelOpen: false,
			lastEventId: '',
			streaming: false,
			sseConnected: false,
			pollError: null,
		});
	},
	async toggleRemote() {
		const {state, loggedIn} = get();
		if (loggedIn || (state !== 'stopped' && state !== 'error')) {
			await get().stopRemote();
			return;
		}
		if (state === 'error') {
			await get().stopRemote();
		}
		await get().startRemote();
	},
	async hydrateRemote() {
		const epoch = pollEpoch;
		try {
			const st = await channelApi().status('', {
				omitJobs: true,
				streamFrom: 0,
			});
			if (epoch !== pollEpoch) {
				return;
			}
			if (st.state === 'stopped' && !st.logged_in) {
				return;
			}
			applyEvents(st.events ?? []);
			const streamApplied = st.streaming ? applyStreamPayload(st) : true;
			set({
				state: st.state,
				loggedIn: st.logged_in,
				hasQr: st.has_qr,
				error: st.error,
				hint: st.hint ?? null,
				qrRev: st.qr_rev ?? 0,
				pollError: pollIssueFromStatus(st),
				streaming: streamApplied ? Boolean(st.streaming) : false,
				panelOpen: st.state !== 'logged_in' && st.state !== 'stopped',
			});
		} catch {
			/* 后端未起或刷新时离线 */
		}
	},
	async pollRemote(opts) {
		if (pollInFlight) {
			return;
		}
		const epoch = pollEpoch;
		const {state, lastEventId, sseConnected, loggedIn} = get();
		if (state === 'stopped' && !get().panelOpen) {
			return;
		}
		const heartbeat = Boolean(opts?.heartbeat);
		if (sseConnected && loggedIn && !heartbeat) {
			return;
		}
		pollInFlight = true;
		try {
			const st = await channelApi().status(lastEventId, {
				omitJobs: true,
				streamFrom: heartbeat || !sseConnected ? streamFrom : undefined,
			});
			if (epoch !== pollEpoch) {
				return;
			}
			if (!sseConnected || heartbeat) {
				const events = st.events ?? [];
				if (events.length) {
					applyEvents(events);
				}
			}
			let streamApplied = true;
			if (!sseConnected) {
				streamApplied = applyStreamPayload(st);
			}
			const events = st.events ?? [];
			const last = events.length ? events[events.length - 1]!.id : lastEventId;
			const nextState =
				get().busy && st.state === 'stopped' ? get().state : st.state;
			const keepPanel =
				get().panelOpen &&
				!st.logged_in &&
				st.state !== 'logged_in';
			const next = {
				state: nextState,
				loggedIn: st.logged_in,
				hasQr: st.has_qr,
				error: st.error,
				hint: st.hint ?? null,
				lastEventId: last,
				qrRev: st.qr_rev ?? get().qrRev,
				panelOpen: keepPanel,
				streaming: sseConnected
					? get().streaming
					: streamApplied && Boolean(st.streaming),
				pollError: pollIssueFromStatus(st),
			};
			const cur = get();
			if (
				cur.state === next.state &&
				cur.loggedIn === next.loggedIn &&
				cur.hasQr === next.hasQr &&
				cur.error === next.error &&
				cur.hint === next.hint &&
				cur.lastEventId === next.lastEventId &&
				cur.qrRev === next.qrRev &&
				cur.panelOpen === next.panelOpen &&
				cur.streaming === next.streaming &&
				cur.pollError === next.pollError
			) {
				return;
			}
			set(next);
		} catch {
			/* 轮询失败时保持现态 */
		} finally {
			pollInFlight = false;
		}
	},
}));

export {filehelperQrUrl};
