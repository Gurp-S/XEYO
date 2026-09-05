import {useEffect, useRef} from 'react';
import {useRemoteStore} from '@/stores/remoteStore';

function pollDelayMs(
	state: string,
	streaming: boolean,
	sseConnected: boolean,
	loggedIn: boolean,
): number | null {
	if (typeof document !== 'undefined' && document.hidden) {
		return null;
	}
	const loginPhase =
		!loggedIn &&
		(state === 'starting' || state === 'qr' || state === 'scanned');
	if (loginPhase) {
		return sseConnected ? 6000 : 400;
	}
	if (sseConnected && loggedIn) {
		return 2_000;
	}
	if (streaming) {
		return 350;
	}
	if (state === 'logged_in') {
		return 3500;
	}
	return 700;
}

/** 远程 HTTP 轮询：QR/登录阶段 + SSE 心跳兜底（已登录约 2s 拉一次事件，防长轮询漏推）。 */
export function RemotePoller() {
	const pollRemote = useRemoteStore(s => s.pollRemote);
	const active = useRemoteStore(s => s.state !== 'stopped' || s.panelOpen);

	const pollRef = useRef(pollRemote);
	pollRef.current = pollRemote;

	useEffect(() => {
		if (!active) {
			return;
		}

		let timer = 0;
		let stopped = false;

		const clear = () => {
			if (timer) {
				window.clearTimeout(timer);
				timer = 0;
			}
		};

		const snapshot = () => useRemoteStore.getState();

		const heartbeat = () => {
			const s = snapshot();
			return s.sseConnected && s.loggedIn;
		};

		const schedule = () => {
			clear();
			if (stopped) {
				return;
			}
			const s = snapshot();
			const ms = pollDelayMs(
				s.state,
				s.streaming,
				s.sseConnected,
				s.loggedIn,
			);
			if (ms == null) {
				return;
			}
			timer = window.setTimeout(() => {
				void pollRef
					.current({heartbeat: heartbeat()})
					.then(() => {
						if (!stopped) {
							schedule();
						}
					});
			}, ms);
		};

		void pollRef.current({heartbeat: heartbeat()}).then(() => {
			if (!stopped) {
				schedule();
			}
		});

		const onVis = () => {
			if (stopped) {
				return;
			}
			if (document.hidden) {
				clear();
				return;
			}
			void pollRef.current({heartbeat: heartbeat()}).then(() => {
				if (!stopped) {
					schedule();
				}
			});
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			stopped = true;
			clear();
			document.removeEventListener('visibilitychange', onVis);
		};
	}, [active]);

	return null;
}
