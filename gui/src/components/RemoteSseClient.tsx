import {useEffect, useRef} from 'react';
import {apiUrl} from '@/lib/apiBase';
import {useRemoteStore} from '@/stores/remoteStore';
import {useSettingsStore} from '@/stores/settingsStore';

/** SSE 推送：入站 / delta / status / outbound / state。已登录时替代高频 HTTP poll。 */
export function RemoteSseClient() {
	const active = useRemoteStore(
		s => s.state !== 'stopped' || s.panelOpen,
	);
	const handleSse = useRemoteStore(s => s.handleSsePayload);
	const setSseConnected = useRemoteStore(s => s.setSseConnected);
	const remoteChannel = useSettingsStore(s => s.remoteChannel);

	const handleRef = useRef(handleSse);
	handleRef.current = handleSse;
	const setConnRef = useRef(setSseConnected);
	setConnRef.current = setSseConnected;

	useEffect(() => {
		if (!active) {
			setConnRef.current(false);
			return;
		}

		let es: EventSource | null = null;
		let retryTimer = 0;
		let stopped = false;

		const connect = () => {
			if (stopped) {
				return;
			}
			es?.close();
			const path =
				remoteChannel === 'ilink'
					? '/v1/ilink/events'
					: '/v1/filehelper/events';
			es = new EventSource(apiUrl(path));

			es.addEventListener('open', () => {
				setConnRef.current(true);
			});

			const onPayload = (ev: MessageEvent<string>) => {
				try {
					const data = JSON.parse(ev.data) as Record<string, unknown>;
					handleRef.current(ev.type, data);
				} catch {
					/* 忽略畸形帧 */
				}
			};

			for (const name of ['state', 'event', 'delta', 'tool'] as const) {
				es.addEventListener(name, onPayload);
			}

			es.onerror = () => {
				setConnRef.current(false);
				es?.close();
				es = null;
				if (!stopped) {
					retryTimer = window.setTimeout(connect, 1500);
				}
			};
		};

		connect();

		return () => {
			stopped = true;
			setConnRef.current(false);
			if (retryTimer) {
				window.clearTimeout(retryTimer);
			}
			es?.close();
		};
	}, [active, remoteChannel]);

	return null;
}
