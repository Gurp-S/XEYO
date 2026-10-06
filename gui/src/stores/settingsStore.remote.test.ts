import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');

import {useSettingsStore} from './settingsStore';

/**
 * 远程通道选择已删除（只保留 iLink）后必须守住的不变量：
 * 旧 localStorage 里存着的 remoteChannel（含 "filehelper"）不能阻断设置加载，
 * 也不能把该字段复活回 state。
 */
describe('legacy remoteChannel storage', () => {
	beforeEach(() => {
		localStorage.clear();
	});

	it('hydrates without the removed remoteChannel field', () => {
		useSettingsStore.getState().hydrate();
		expect('remoteChannel' in useSettingsStore.getState()).toBe(false);
	});

	it('ignores a legacy filehelper value and still loads other settings', () => {
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
		const st = useSettingsStore.getState();
		expect(st.provider).toBe('deepseek');
		expect(st.sidebarWidth).toBe(248);
		expect('remoteChannel' in st).toBe(false);
	});
});
