/**
 * 本地模型 provider（'local'）门禁测试。
 *
 * 'local' 是正式功能（2026-09-14 起从 localTestGate 的 dev 门禁里摘出来）：
 * 生产构建同样可识别、同样允许空 Key——要不要用它由用户在本机决定
 * （设置 → 模型与账号 → 本地模型）。'fake' 仍受 dev 门禁管理。
 *
 * 判定实体是 `localTestGate.isKnownProvider`；`settingsStore.isProviderId` 只转发它，
 * 测试替身也转发它，所以这里的断言打在真实规则上。
 */
import {beforeEach, describe, expect, it} from 'vitest';
import {
	allowsEmptyApiKey,
	isKnownProvider,
	isLocalProvider,
	isTestProvider,
} from '@/lib/localTestGate';
import {isProviderId} from '@/stores/settingsStore';

describe('local provider gate', () => {
	beforeEach(() => {
		window.localStorage.clear();
	});

	it('local 不受 dev 门禁影响：识别与空 Key 恒放行', () => {
		expect(isLocalProvider('local')).toBe(true);
		expect(allowsEmptyApiKey('local')).toBe(true);
		expect(isKnownProvider('local')).toBe(true);
		expect(isProviderId('local')).toBe(true);
	});

	it('门禁关时 local 仍可用、fake 仍被拒', () => {
		expect(isTestProvider('local')).toBe(false);
		expect(isTestProvider('fake')).toBe(false);
		expect(allowsEmptyApiKey('fake')).toBe(false);
		expect(isKnownProvider('fake')).toBe(false);
		// 同一时刻两者结论相反，证明 'local' 已不属于 dev 门禁管辖。
		expect(isKnownProvider('local')).toBe(true);
	});

	it('云端 provider 与非法值口径不变', () => {
		expect(isKnownProvider('deepseek')).toBe(true);
		expect(isKnownProvider('openai')).toBe(true);
		expect(isKnownProvider('anthropic')).toBe(true);
		expect(isProviderId('unknown')).toBe(false);
		expect(isLocalProvider('localhost')).toBe(false);
		expect(isLocalProvider('')).toBe(false);
		expect(isLocalProvider(null)).toBe(false);
		expect(allowsEmptyApiKey('deepseek')).toBe(false);
	});
});
