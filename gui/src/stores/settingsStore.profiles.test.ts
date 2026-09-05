import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');

import {profileModelIds, useSettingsStore} from './settingsStore';

describe('model profiles', () => {
	beforeEach(() => {
		localStorage.clear();
		useSettingsStore.setState({
			provider: 'deepseek',
			model: 'deepseek-v4-flash',
			apiKey: '',
			baseUrl: '',
			profiles: [],
			activeProfileId: '',
		});
	});

	it('migrates a single legacy config into one local profile', () => {
		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'openai',
				model: 'gpt-4o-mini',
				apiKey: 'sk-legacykeyxxxx',
				baseUrl: 'https://api.openai.com/v1',
				theme: 'paper',
			}),
		);
		useSettingsStore.getState().hydrate();
		const st = useSettingsStore.getState();
		expect(st.profiles).toHaveLength(1);
		expect(st.provider).toBe('openai');
		expect(st.model).toBe('gpt-4o-mini');
		expect(st.apiKey).toBe('sk-legacykeyxxxx');
		expect(st.profiles[0].id).toBe(st.activeProfileId);
		// 旧单模型自动迁移为 models[0]
		expect(st.profiles[0].models?.map(m => m.id)).toEqual(['gpt-4o-mini']);
		expect(profileModelIds(st.profiles[0])).toEqual(['gpt-4o-mini']);
	});

	it('adds a second profile, selects it, and keeps the first', () => {
		useSettingsStore.getState().hydrate();
		useSettingsStore.getState().update({apiKey: 'sk-firstkeyaaaa'});
		const firstId = useSettingsStore.getState().activeProfileId;
		const second = useSettingsStore.getState().addProfile({
			provider: 'deepseek',
			model: 'deepseek-v4-pro',
			apiKey: 'sk-secondkeybbbb',
		});
		expect(useSettingsStore.getState().profiles).toHaveLength(2);
		expect(useSettingsStore.getState().activeProfileId).toBe(second);
		expect(useSettingsStore.getState().model).toBe('deepseek-v4-pro');
		expect(profileModelIds(useSettingsStore.getState().profiles[1])).toEqual([
			'deepseek-v4-pro',
		]);
		useSettingsStore.getState().selectProfile(firstId);
		expect(useSettingsStore.getState().apiKey).toBe('sk-firstkeyaaaa');
		expect(useSettingsStore.getState().model).toBe('deepseek-v4-flash');
	});

	it('refuses to remove the last profile', () => {
		useSettingsStore.getState().hydrate();
		const id = useSettingsStore.getState().activeProfileId;
		useSettingsStore.getState().removeProfile(id);
		expect(useSettingsStore.getState().profiles).toHaveLength(1);
	});

	it('profileModelIds returns the registered model id set', () => {
		// 单模型：回退到 [model]
		expect(
			profileModelIds({
				id: 'p_single',
				provider: 'deepseek' as const,
				model: 'deepseek-v4-flash',
				apiKey: '',
				baseUrl: '',
			}),
		).toEqual(['deepseek-v4-flash']);
		// 多模型：取 models 集合
		const multi = {
			id: 'p_multi',
			provider: 'deepseek' as const,
			model: 'b',
			apiKey: '',
			baseUrl: '',
			models: [{id: 'a'}, {id: 'b'}, {id: 'c'}],
		};
		expect(profileModelIds(multi)).toEqual(['a', 'b', 'c']);
		// 无模型、无可迁移字段：返回空数组
		expect(
			profileModelIds({
				id: 'p_empty',
				provider: 'deepseek' as const,
				model: '',
				apiKey: '',
				baseUrl: '',
			}),
		).toEqual([]);
	});

	it('migrates a single legacy model (with limits) into models[0]', () => {
		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'deepseek',
				model: 'deepseek-v4-flash',
				apiKey: 'sk-x',
				baseUrl: 'https://api.deepseek.com/v1',
				profiles: [
					{
						id: 'p_1',
						provider: 'deepseek',
						model: 'deepseek-v4-flash',
						apiKey: 'sk-x',
						baseUrl: 'https://api.deepseek.com/v1',
						contextLimit: 131072,
						maxOutputTokens: 8192,
					},
				],
				activeProfileId: 'p_1',
			}),
		);
		useSettingsStore.getState().hydrate();
		const st = useSettingsStore.getState();
		const prof = st.profiles[0];
		expect(prof.models?.map(m => m.id)).toEqual(['deepseek-v4-flash']);
		expect(prof.models?.[0].contextLimit).toBe(131072);
		expect(prof.models?.[0].maxOutputTokens).toBe(8192);
		expect(profileModelIds(prof)).toEqual(['deepseek-v4-flash']);
	});

	it('adds multiple models to a profile via updateProfile', () => {
		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'deepseek',
				model: 'deepseek-v4-flash',
				apiKey: 'sk-base',
				baseUrl: 'https://api.deepseek.com/v1',
				profiles: [
					{
						id: 'p_1',
						provider: 'deepseek',
						model: 'deepseek-v4-flash',
						apiKey: 'sk-base',
						baseUrl: 'https://api.deepseek.com/v1',
					},
				],
				activeProfileId: 'p_1',
			}),
		);
		useSettingsStore.getState().hydrate();
		const id = useSettingsStore.getState().profiles[0].id;
		useSettingsStore.getState().updateProfile(id, {
			model: 'deepseek-v4-pro',
			models: [
				{id: 'deepseek-v4-flash', contextLimit: 65536},
				{id: 'deepseek-v4-pro', contextLimit: 131072},
			],
		});
		const prof = useSettingsStore.getState().profiles.find(p => p.id === id)!;
		expect(prof.models?.map(m => m.id)).toEqual([
			'deepseek-v4-flash',
			'deepseek-v4-pro',
		]);
		expect(prof.model).toBe('deepseek-v4-pro');
		expect(profileModelIds(prof)).toEqual([
			'deepseek-v4-flash',
			'deepseek-v4-pro',
		]);
		// 顶层激活模型随之切换
		expect(useSettingsStore.getState().model).toBe('deepseek-v4-pro');
	});

	it('removes a model and falls the active model back to a valid one', () => {
		localStorage.setItem(
			'xeyo-settings',
			JSON.stringify({
				provider: 'deepseek',
				model: 'deepseek-v4-flash',
				apiKey: 'sk-base',
				baseUrl: 'https://api.deepseek.com/v1',
				profiles: [
					{
						id: 'p_1',
						provider: 'deepseek',
						model: 'deepseek-v4-flash',
						apiKey: 'sk-base',
						baseUrl: 'https://api.deepseek.com/v1',
					},
				],
				activeProfileId: 'p_1',
			}),
		);
		useSettingsStore.getState().hydrate();
		const id = useSettingsStore.getState().profiles[0].id;
		useSettingsStore.getState().updateProfile(id, {
			model: 'b',
			models: [{id: 'a'}, {id: 'b'}],
		});
		expect(profileModelIds(useSettingsStore.getState().profiles[0])).toEqual([
			'a',
			'b',
		]);
		// 删除激活模型 b → 回落到第一个模型 a
		useSettingsStore.getState().updateProfile(id, {models: [{id: 'a'}]});
		const prof = useSettingsStore.getState().profiles[0];
		expect(prof.models?.map(m => m.id)).toEqual(['a']);
		expect(prof.model).toBe('a');
		expect(useSettingsStore.getState().model).toBe('a');
	});
});
