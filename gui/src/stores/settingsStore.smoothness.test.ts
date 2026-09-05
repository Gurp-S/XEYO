import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');

import {__resetPrefersReducedMotionCacheForTests} from '@/lib/prefersReducedMotion';
import {useSettingsStore} from './settingsStore';

function stubMotion(reduce: boolean) {
	vi.stubGlobal(
		'matchMedia',
		vi.fn((query: string) => ({
			matches: reduce && String(query).includes('prefers-reduced-motion'),
			media: query,
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			addListener: vi.fn(),
			removeListener: vi.fn(),
			dispatchEvent: vi.fn(),
		})),
	);
	__resetPrefersReducedMotionCacheForTests();
}

describe('smoothness persistence', () => {
	beforeEach(() => {
		localStorage.clear();
		document.documentElement.dataset.smoothness = '';
		stubMotion(false);
		useSettingsStore.setState({smoothness: true});
	});

	it('defaults on; missing key hydrates to on', () => {
		expect(useSettingsStore.getState().smoothness).not.toBe(false);
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().smoothness).toBe(true);
		expect(document.documentElement.dataset.smoothness).toBe('on');

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
		expect(useSettingsStore.getState().smoothness).toBe(true);
	});

	it('persists off and hydrates dataset', () => {
		useSettingsStore.getState().update({smoothness: false});
		expect(useSettingsStore.getState().smoothness).toBe(false);
		expect(document.documentElement.dataset.smoothness).toBe('off');
		const raw = JSON.parse(
			localStorage.getItem('xeyo-settings') ?? '{}',
		) as {smoothness?: boolean};
		expect(raw.smoothness).toBe(false);

		useSettingsStore.setState({smoothness: true});
		useSettingsStore.getState().hydrate();
		expect(useSettingsStore.getState().smoothness).toBe(false);
		expect(document.documentElement.dataset.smoothness).toBe('off');
	});

	it('prefers-reduced-motion forces data-smoothness off', () => {
		stubMotion(true);
		useSettingsStore.getState().update({smoothness: true});
		expect(useSettingsStore.getState().smoothness).toBe(true);
		expect(document.documentElement.dataset.smoothness).toBe('off');
	});
});
