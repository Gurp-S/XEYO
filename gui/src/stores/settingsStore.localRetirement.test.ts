import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');
import {useSettingsStore} from './settingsStore';

const retired = {id: 'old-local', provider: 'local', model: 'old-gguf', apiKey: '', baseUrl: 'http://127.0.0.1:8080/v1'};
const cloud = {id: 'cloud', provider: 'openai', model: 'cloud-model', apiKey: 'cloud-key', baseUrl: 'https://example.com/v1'};

describe('retired managed local model settings', () => {
	beforeEach(() => localStorage.clear());
	afterEach(() => vi.unstubAllEnvs());

	function hydrate(value: object) {
		localStorage.setItem('xeyo-settings', JSON.stringify(value));
		useSettingsStore.getState().hydrate();
		return useSettingsStore.getState();
	}

	it('removes old local profiles and selects the remaining cloud account', () => {
		const state = hydrate({...retired, profiles: [retired, cloud], activeProfileId: retired.id});
		expect(state.profiles.map(p => p.id)).toEqual(['cloud']);
		expect(state).toMatchObject({provider: cloud.provider, model: cloud.model, apiKey: cloud.apiKey, baseUrl: cloud.baseUrl, activeProfileId: 'cloud'});
	});

	it.each([undefined, [retired]])('resets the retired endpoint instead of relabeling it as a cloud account (%j)', profiles => {
		const state = hydrate({...retired, profiles, theme: 'paper'});
		expect(state.provider).toBe('deepseek');
		expect(state.model).not.toBe('old-gguf');
		expect(state.baseUrl).not.toBe(retired.baseUrl);
		expect(state.apiKey).toBe('');
		expect(state.theme).toBe('paper');
	});

	it('preserves explicitly enabled development test transport', () => {
		localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
		const state = hydrate({...retired, profiles: [retired]});
		expect(state.provider).toBe('local');
		expect(state.baseUrl).toBe(retired.baseUrl);
	});

	it('does not allow the test switch to restore the feature in production', () => {
		vi.stubEnv('DEV', false);
		localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
		expect(hydrate(retired).provider).toBe('deepseek');
	});
});
