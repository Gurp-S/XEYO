import {describe, expect, it} from 'vitest';
import {
	errorBannerMatchesActiveSession,
	pendingMatchesActiveSession,
	sessionErrorBannerPatch,
	visibleErrorBanner,
} from './pendingForSession';

describe('pendingMatchesActiveSession', () => {
	it('matches when session ids equal', () => {
		expect(pendingMatchesActiveSession('s1', 's1')).toBe(true);
	});

	it('rejects when session ids differ', () => {
		expect(pendingMatchesActiveSession('s1', 's2')).toBe(false);
	});

	it('rejects when active session missing', () => {
		expect(pendingMatchesActiveSession('s1', null)).toBe(false);
	});

	it('allows missing pending session id (legacy)', () => {
		expect(pendingMatchesActiveSession(undefined, 's1')).toBe(true);
	});
});

describe('sessionErrorBannerPatch', () => {
	it('binds message to session', () => {
		expect(sessionErrorBannerPatch('s1', 'boom')).toEqual({
			errorBanner: 'boom',
			errorBannerSessionId: 's1',
		});
	});

	it('clears banner when message empty', () => {
		expect(sessionErrorBannerPatch('s1', null)).toEqual({
			errorBanner: null,
			errorBannerSessionId: null,
		});
	});
});

describe('visibleErrorBanner', () => {
	it('hides banner from another session', () => {
		expect(
			visibleErrorBanner('boom', 's1', 's2'),
		).toBeNull();
	});

	it('shows global banner on any active session', () => {
		expect(
			visibleErrorBanner('settings', null, 's2'),
		).toBe('settings');
	});

	it('shows session banner only on matching active session', () => {
		expect(
			errorBannerMatchesActiveSession('s1', 's1'),
		).toBe(true);
		expect(visibleErrorBanner('err', 's1', 's1')).toBe('err');
	});
});
