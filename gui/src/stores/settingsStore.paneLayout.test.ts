import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');

import {useSettingsStore} from './settingsStore';

describe('paneLayout persistence', () => {
	beforeEach(() => {
		localStorage.clear();
		document.documentElement.dataset.paneLayout = '';
		useSettingsStore.setState({paneLayout: 'islands'});
	});

	it('missing key hydrates to islands and paints dataset', () => {
		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'deepseek',
				model: 'deepseek-v4-flash',
				theme: 'paper',
				bgOpacity: 70,
				bgBlur: 12,
				sidebarWidth: 248,
			}),
		);
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().paneLayout).toBe('islands');
		expect(document.documentElement.dataset.paneLayout).toBe('islands');
	});

	it('persists chosen layout and hydrates dataset', () => {
		useSettingsStore.getState().update({paneLayout: 'dotted'});
		expect(useSettingsStore.getState().paneLayout).toBe('dotted');
		expect(document.documentElement.dataset.paneLayout).toBe('dotted');
		const raw = JSON.parse(
			localStorage.getItem('xeyo-settings') ?? '{}',
		) as {paneLayout?: string};
		expect(raw.paneLayout).toBe('dotted');

		useSettingsStore.setState({paneLayout: 'classic'});
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().paneLayout).toBe('dotted');
		expect(document.documentElement.dataset.paneLayout).toBe('dotted');
	});

	it('illegal stored value falls back to islands', () => {
		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({paneLayout: 'neon-glow'}),
		);
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().paneLayout).toBe('islands');
		expect(document.documentElement.dataset.paneLayout).toBe('islands');
	});
});
