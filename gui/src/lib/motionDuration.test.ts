import {afterEach, describe, expect, it} from 'vitest';
import dockPresenceSrc from '../components/DockPresence.tsx?raw';
import settingsModalSrc from '../components/SettingsModal.tsx?raw';
import {
	FALLBACK_DURATION_MS,
	PRESENCE_EXIT_MARGIN_MS,
	cssDurationMs,
	presenceExitMs,
} from './motionDuration';

const ROOT = document.documentElement;

describe('cssDurationMs 从 CSS 令牌读真值，而非在 TS 里另写一份', () => {
	afterEach(() => {
		ROOT.style.removeProperty('--duration-fast');
		ROOT.style.removeProperty('--duration-base');
	});

	it('读 documentElement 上的 --duration-base', () => {
		ROOT.style.setProperty('--duration-base', '333ms');
		expect(cssDurationMs('base')).toBe(333);
	});

	it('读 --duration-fast', () => {
		ROOT.style.setProperty('--duration-fast', '90ms');
		expect(cssDurationMs('fast')).toBe(90);
	});

	it('CSS 改值即自动跟随 —— 这正是消除两侧漂移的关键', () => {
		ROOT.style.setProperty('--duration-base', '420ms');
		expect(presenceExitMs(cssDurationMs('base'))).toBe(440);
	});

	it('非法值回落兜底常量而不是抛错', () => {
		ROOT.style.setProperty('--duration-base', 'bogus');
		expect(cssDurationMs('base')).toBe(FALLBACK_DURATION_MS.base);
	});

	it('兜底常量与 tokens.css 现值一致（改 CSS 后须同步此处）', () => {
		expect(FALLBACK_DURATION_MS).toEqual({fast: 140, base: 200});
	});
});

describe('presence 退出延迟恒不小于容器过渡时长', () => {
	it('加正余量', () => {
		expect(PRESENCE_EXIT_MARGIN_MS).toBeGreaterThan(0);
		expect(presenceExitMs(200)).toBe(200 + PRESENCE_EXIT_MARGIN_MS);
	});

	it('对全部在用时长的样本成立', () => {
		for (const ms of [80, 120, 140, 160, 200, 220, 420]) {
			expect(presenceExitMs(ms)).toBeGreaterThanOrEqual(ms);
		}
	});
});

describe('调用点不得写死与容器时长脱钩的裸数字', () => {
	it('DockPresence 走 cssDurationMs + presenceExitMs', () => {
		expect(dockPresenceSrc).toContain("cssDurationMs('base')");
		expect(dockPresenceSrc).toContain('presenceExitMs(');
		// 裸数字（曾是 180）导致末 20ms 截断，禁止回归
		expect(dockPresenceSrc).not.toMatch(/usePresence\([^)]*?smoothness\s*\?\s*\d+/);
	});

	it('SettingsModal 走 cssDurationMs + presenceExitMs', () => {
		expect(settingsModalSrc).toContain("cssDurationMs('base')");
		expect(settingsModalSrc).toContain('presenceExitMs(');
		// 裸数字（曾是 160）导致末 40ms 截断，禁止回归
		expect(settingsModalSrc).not.toMatch(/usePresence\(open,\s*\d+/);
	});
});
