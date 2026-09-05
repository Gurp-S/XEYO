/** 桌面只镜像「最近一条入站」对应的微信会话。无 session_id 的旧载荷一律放行。 */

export type RemotePayloadKind = 'inbound' | 'stream' | 'outbound' | 'tool' | 'other';

export function payloadSessionId(
	data: Record<string, unknown> | undefined | null,
): string {
	if (!data) {
		return '';
	}
	for (const key of ['stream_session_id', 'session_id', 'last_session_id'] as const) {
		const raw = data[key];
		if (typeof raw === 'string' && raw.trim()) {
			return raw.trim();
		}
	}
	return '';
}

export function shouldApplyRemotePayload(opts: {
	kind: RemotePayloadKind;
	incomingSid: string;
	mirrorSid: string;
}): {apply: boolean; mirrorSid: string} {
	const incoming = (opts.incomingSid || '').trim();
	if (!incoming) {
		return {apply: true, mirrorSid: opts.mirrorSid};
	}
	if (opts.kind === 'inbound') {
		return {apply: true, mirrorSid: incoming};
	}
	if (!opts.mirrorSid) {
		return {apply: true, mirrorSid: incoming};
	}
	return {apply: incoming === opts.mirrorSid, mirrorSid: opts.mirrorSid};
}

let mirrorSid = '';

export function getRemoteMirrorSession(): string {
	return mirrorSid;
}

export function resetRemoteMirrorSession(): void {
	mirrorSid = '';
}

export function gateRemotePayload(
	kind: RemotePayloadKind,
	data: Record<string, unknown> | undefined | null,
): boolean {
	const next = shouldApplyRemotePayload({
		kind,
		incomingSid: payloadSessionId(data ?? undefined),
		mirrorSid,
	});
	mirrorSid = next.mirrorSid;
	return next.apply;
}
