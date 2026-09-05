/**
 * fake provider（Playwright 全栈测试）门禁测试。
 * 'fake' 与 'local' 一样受 localTestGate 管理：仅 DEV 构建 + XEYO_ENABLE_LOCAL_TEST=1
 * 时放行（空 Key 合法、isProviderId 识别），否则归一化为 deepseek。
 */
import {beforeEach, describe, expect, it} from 'vitest';
import {allowsEmptyApiKey, isTestProvider} from '@/lib/localTestGate';
import {isProviderId as isProviderIdStore} from '@/stores/settingsStore';

describe('fake test-provider gate', () => {
	beforeEach(() => {
		window.localStorage.clear();
	});

	it('gate off: fake rejected', () => {
		expect(isTestProvider('fake')).toBe(false);
		expect(allowsEmptyApiKey('fake')).toBe(false);
		expect(isProviderIdStore('fake')).toBe(false);
	});

	it('gate on: fake accepted, empty key allowed', () => {
		window.localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
		expect(isTestProvider('fake')).toBe(true);
		expect(allowsEmptyApiKey('fake')).toBe(true);
		expect(isProviderIdStore('fake')).toBe(true);
	});

	it('gate on still rejects unknown provider', () => {
		window.localStorage.setItem('XEYO_ENABLE_LOCAL_TEST', '1');
		expect(isProviderIdStore('unknown')).toBe(false);
	});
});
