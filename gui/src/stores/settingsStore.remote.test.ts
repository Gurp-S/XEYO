import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');

import {
	normalizeRemoteChannel,
	useSettingsStore,
} from './settingsStore';

describe('remoteChannel persistence', () => {
	beforeEach(() => {
		localStorage.clear();
		useSettingsStore.setState({remoteChannel: 'ilink'});
	});

	it('defaults to ilink; filehelper stays when chosen', () => {
		expect(useSettingsStore.getState().remoteChannel).toBe('ilink');
		expect(normalizeRemoteChannel('ilink')).toBe('ilink');
		expect(normalizeRemoteChannel('filehelper')).toBe('filehelper');
		expect(normalizeRemoteChannel('nope')).toBe('ilink');
		expect(normalizeRemoteChannel(undefined)).toBe('ilink');
	});

	it('empty or legacy storage without remoteChannel hydrates to ilink', () => {
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().remoteChannel).toBe('ilink');

		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'deepseek',
				model: 'deepseek-v4-flash',
				apiKey: '',
				baseUrl: '',
				theme: 'paper',
				bgOpacity: 70,
				bgBlur: 12,
				sidebarWidth: 248,
			}),
		);
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().remoteChannel).toBe('ilink');
	});

	it('persists ilink to localStorage', () => {
		useSettingsStore.getState().update({remoteChannel: 'ilink'});
		expect(useSettingsStore.getState().remoteChannel).toBe('ilink');
		const raw = JSON.parse(localStorage.getItem('xeyo-settings') ?? '{}') as {
			remoteChannel?: string;
		};
		expect(raw.remoteChannel).toBe('ilink');
	});

	it('hydrates ilink from localStorage', () => {
		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'deepseek',
				model: 'deepseek-v4-flash',
				apiKey: '',
				baseUrl: '',
				theme: 'paper',
				remoteChannel: 'ilink',
				bgOpacity: 70,
				bgBlur: 12,
				sidebarWidth: 248,
			}),
		);
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().remoteChannel).toBe('ilink');
	});

	it('keeps filehelper when already saved', () => {
		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'deepseek',
				model: 'deepseek-v4-flash',
				apiKey: '',
				baseUrl: '',
				theme: 'paper',
				remoteChannel: 'filehelper',
				bgOpacity: 70,
				bgBlur: 12,
				sidebarWidth: 248,
			}),
		);
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().remoteChannel).toBe('filehelper');
	});
});
