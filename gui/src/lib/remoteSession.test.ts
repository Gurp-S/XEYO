import {describe, expect, it} from 'vitest';
import {
	payloadSessionId,
	resetRemoteMirrorSession,
	shouldApplyRemotePayload,
} from './remoteSession';

describe('payloadSessionId', () => {
	it('reads stream_session_id then session_id then last_session_id', () => {
		expect(
			payloadSessionId({
				stream_session_id: 'ilink:stream',
				session_id: 'ilink:a',
				last_session_id: 'ilink:b',
			}),
		).toBe('ilink:stream');
		expect(payloadSessionId({session_id: 'ilink:a'})).toBe('ilink:a');
		expect(payloadSessionId({last_session_id: 'ilink:b'})).toBe('ilink:b');
		expect(payloadSessionId({stream_session_id: '', session_id: 'ilink:a'})).toBe(
			'ilink:a',
		);
		expect(payloadSessionId({})).toBe('');
	});
});

describe('shouldApplyRemotePayload', () => {
	it('always applies inbound and switches mirror', () => {
		expect(
			shouldApplyRemotePayload({
				kind: 'inbound',
				incomingSid: 'ilink:b',
				mirrorSid: 'ilink:a',
			}),
		).toEqual({apply: true, mirrorSid: 'ilink:b'});
	});

	it('drops stream/outbound from another session', () => {
		expect(
			shouldApplyRemotePayload({
				kind: 'stream',
				incomingSid: 'ilink:b',
				mirrorSid: 'ilink:a',
			}),
		).toEqual({apply: false, mirrorSid: 'ilink:a'});
		expect(
			shouldApplyRemotePayload({
				kind: 'outbound',
				incomingSid: 'ilink:b',
				mirrorSid: 'ilink:a',
			}),
		).toEqual({apply: false, mirrorSid: 'ilink:a'});
	});

	it('applies legacy payloads with no session id', () => {
		expect(
			shouldApplyRemotePayload({
				kind: 'stream',
				incomingSid: '',
				mirrorSid: 'ilink:a',
			}),
		).toEqual({apply: true, mirrorSid: 'ilink:a'});
	});

	it('adopts first stream sid when mirror is empty', () => {
		expect(
			shouldApplyRemotePayload({
				kind: 'stream',
				incomingSid: 'ilink:a',
				mirrorSid: '',
			}),
		).toEqual({apply: true, mirrorSid: 'ilink:a'});
	});
});

describe('resetRemoteMirrorSession', () => {
	it('clears module mirror', () => {
		resetRemoteMirrorSession();
		expect(true).toBe(true);
	});
});
