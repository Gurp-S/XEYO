import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.unmock('@/stores/settingsStore');

import {
	registeredContextLimitOf,
	registeredWindowFromSettings,
	resolveWindowLimit,
	windowUsagePercent,
} from './modelWindow';
import {
	profileContextLimitFor,
	useSettingsStore,
	type ModelProfile,
} from '@/stores/settingsStore';

const profile = (over: Partial<ModelProfile> = {}): ModelProfile => ({
	id: 'p_a',
	provider: 'deepseek',
	model: 'deepseek-chat',
	apiKey: '',
	baseUrl: '',
	...over,
});

describe('registeredContextLimitOf（设置登记值 = 窗口口径首选）', () => {
	it('按当前激活模型取 models[] 里各自登记的窗口', () => {
		const p = profile({
			model: 'deepseek-chat',
			contextLimit: 65_536,
			models: [
				{id: 'deepseek-chat', contextLimit: 128_000},
				{id: 'deepseek-reasoner', contextLimit: 200_000},
			],
		});
		expect(registeredContextLimitOf(p)).toBe(128_000);
		// 换激活模型 → 立即换窗口（不再停留在账号级旧值）。
		expect(registeredContextLimitOf(p, 'deepseek-reasoner')).toBe(200_000);
	});

	it('模型没登记窗口时退回账号旧单值字段；仍无 → undefined（绝不猜）', () => {
		expect(
			registeredContextLimitOf(
				profile({contextLimit: 32_768, models: [{id: 'x'}]}),
				'x',
			),
		).toBe(32_768);
		expect(
			registeredContextLimitOf(profile({models: [{id: 'x'}]}), 'x'),
		).toBeUndefined();
		expect(registeredContextLimitOf(undefined)).toBeUndefined();
	});

	it('0 / 负数 / 非数字登记值视为未登记', () => {
		expect(
			registeredContextLimitOf(
				profile({models: [{id: 'x', contextLimit: 0}]}),
				'x',
			),
		).toBeUndefined();
	});

	it('profileContextLimitFor 与 modelWindow 同一实现（不再两套口径）', () => {
		const p = profile({
			contextLimit: 65_536,
			models: [{id: 'deepseek-chat', contextLimit: 128_000}],
		});
		expect(profileContextLimitFor(p)).toBe(registeredContextLimitOf(p));
	});
});

describe('resolveWindowLimit / windowUsagePercent', () => {
	it('用户填写 > 厂商缓存（用户意图优先）', () => {
		expect(resolveWindowLimit({registered: 128_000, vendorCached: 64_000})).toBe(
			128_000,
		);
	});

	it('用户没填才用厂商缓存；两者都没有 → undefined', () => {
		expect(resolveWindowLimit({vendorCached: 64_000})).toBe(64_000);
		expect(resolveWindowLimit({registered: 0, vendorCached: -1})).toBeUndefined();
	});

	it('占用% 永远按给定分母算；分子或分母未知 → undefined', () => {
		expect(windowUsagePercent({contextTokens: 32_000, limit: 128_000})).toBe(25);
		expect(windowUsagePercent({contextTokens: 200_000, limit: 128_000})).toBe(100);
		expect(windowUsagePercent({contextTokens: null, limit: 128_000})).toBeUndefined();
		expect(windowUsagePercent({contextTokens: 10, limit: null})).toBeUndefined();
	});
});

describe('registeredContextLimitFromState（面板订阅的同一个 selector）', () => {
	beforeEach(() => {
		localStorage.clear();
		useSettingsStore.setState({
			provider: 'deepseek',
			model: 'deepseek-chat',
			apiKey: '',
			baseUrl: '',
			profiles: [],
			activeProfileId: '',
		});
	});

	it('新会话（完全没有任何 usage）也能立刻报出窗口', () => {
		const s = useSettingsStore.getState();
		s.addProfile({
			provider: 'deepseek',
			model: 'deepseek-chat',
			apiKey: 'sk-aaaaaaaa',
			models: [{id: 'deepseek-chat', contextLimit: 128_000}],
		});
		expect(
			registeredWindowFromSettings(useSettingsStore.getState()),
		).toBe(128_000);
	});

	it('保存账号改窗口 / 切激活模型 / 切账号 → 派生窗口立即变', () => {
		const st = useSettingsStore.getState();
		const firstId = st.addProfile({
			provider: 'deepseek',
			model: 'deepseek-chat',
			apiKey: 'sk-aaaaaaaa',
			models: [
				{id: 'deepseek-chat', contextLimit: 128_000},
				{id: 'deepseek-reasoner', contextLimit: 200_000},
			],
		});
		const get = () => registeredWindowFromSettings(useSettingsStore.getState());
		expect(get()).toBe(128_000);
		// 1) 同账号内换模型（ModelPicker 走 update({model})）。
		useSettingsStore.getState().update({model: 'deepseek-reasoner'});
		expect(get()).toBe(200_000);
		// 2) 编辑激活账号的窗口登记值。
		useSettingsStore.getState().updateProfile(firstId, {
			models: [
				{id: 'deepseek-chat', contextLimit: 64_000},
				{id: 'deepseek-reasoner', contextLimit: 256_000},
			],
		});
		expect(get()).toBe(256_000);
		// 3) 切到另一个账号。
		const secondId = useSettingsStore.getState().addProfile({
			provider: 'openai',
			model: 'gpt-4o-mini',
			apiKey: 'sk-bbbbbbbb',
			models: [{id: 'gpt-4o-mini', contextLimit: 16_000}],
		});
		useSettingsStore.getState().selectProfile(secondId);
		expect(get()).toBe(16_000);
		useSettingsStore.getState().selectProfile(firstId);
		expect(get()).toBe(256_000);
	});
});
