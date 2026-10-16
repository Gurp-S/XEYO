import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
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
	afterEach(() => vi.unstubAllEnvs());

	it('local 仅在开发测试显式开启时可用', () => {
		window.localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
		expect(isLocalProvider('local')).toBe(true);
		expect(allowsEmptyApiKey('local')).toBe(true);
		expect(isKnownProvider('local')).toBe(true);
		expect(isProviderId('local')).toBe(true);
	});

	it('默认不开放 local 或 fake', () => {
		expect(isTestProvider('local')).toBe(false);
		expect(isTestProvider('fake')).toBe(false);
		expect(allowsEmptyApiKey('fake')).toBe(false);
		expect(isKnownProvider('fake')).toBe(false);
		expect(isKnownProvider('local')).toBe(false);
		expect(allowsEmptyApiKey('local')).toBe(false);
	});

	it('生产构建不能通过旧测试开关恢复本地模型', () => {
		vi.stubEnv('DEV', false);
		window.localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
		expect(isKnownProvider('local')).toBe(false);
		expect(isKnownProvider('fake')).toBe(false);
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
