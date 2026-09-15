/**
 * 设置滚动备份 —— 2026-09-14 账号丢失事故的结构性防线回归。
 *
 * 事故形态：`xeyo-settings` 读不到 → `loadLite` 回落默认值 → `hydrateAsync`
 * 把默认值写回盘 ⇒ 4 个账号（含明文 Key）被永久覆盖、不留痕迹。
 *
 * 这里锁死两条不变量：
 *  1. 主键缺失或不可解析时，必须能被备份救回，而不是回落默认值；
 *  2. 写盘不得用「更穷」的值（默认值 / 半截状态）冲掉好备份。
 *
 * ⚠️ `test/setup.ts` 把整个 settingsStore 换成了替身，所以这里必须用
 * `vi.importActual` 加载真实实现，否则测的是替身。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';

const KEY = 'xeyo-settings';
const BACKUP = 'xeyo-settings.bak';

/** 造一份含 n 个账号的设置值（其余字段由 DEFAULTS 兜住，够用即可）。 */
function settingsJson(n: number, theme = 'paper'): string {
	return JSON.stringify({
		provider: 'deepseek',
		model: 'm0',
		apiKey: '',
		baseUrl: '',
		profiles: Array.from({length: n}, (_, i) => ({
			id: `p${i}`,
			provider: 'deepseek',
			model: `m${i}`,
			apiKey: `key-${i}`,
			baseUrl: '',
		})),
		activeProfileId: 'p0',
		theme,
	});
}

function profileCountIn(raw: string | null): number {
	if (!raw) {
		return -1;
	}
	return (JSON.parse(raw) as {profiles?: unknown[]}).profiles?.length ?? -1;
}

/** hydrate 会派发异步的 hydrateAsync（回写盘），先让它落地再断言。 */
const settle = () => new Promise<void>(resolve => setTimeout(resolve, 0));

async function realStore() {
	return await vi.importActual<typeof import('@/stores/settingsStore')>(
		'@/stores/settingsStore',
	);
}

describe('settingsStore 滚动备份', () => {
	beforeEach(() => {
		window.localStorage.clear();
	});

	it('主键缺失时用备份自愈，并写回主键', async () => {
		window.localStorage.setItem(BACKUP, settingsJson(4, 'platinum'));
		const mod = await realStore();
		mod.useSettingsStore.getState().hydrate();
		await settle();
		const s = mod.useSettingsStore.getState();
		expect(s.profiles).toHaveLength(4);
		expect(s.theme).toBe('platinum');
		// 自愈 = 备份值被写回主键（hydrateAsync 会顺带补齐默认字段，故按语义断言）。
		const restored = window.localStorage.getItem(KEY);
		expect(profileCountIn(restored)).toBe(4);
		expect(
			(JSON.parse(restored as string) as {profiles: {apiKey: string}[]}).profiles.map(
				p => p.apiKey,
			),
		).toEqual(['key-0', 'key-1', 'key-2', 'key-3']);
	});

	it('主键 JSON 损坏时也用备份自愈，而不是回落默认值', async () => {
		window.localStorage.setItem(KEY, '{"provider":"deepseek","profiles":[{"id"');
		window.localStorage.setItem(BACKUP, settingsJson(3, 'graphite'));
		const mod = await realStore();
		mod.useSettingsStore.getState().hydrate();
		await settle();
		const s = mod.useSettingsStore.getState();
		expect(s.profiles).toHaveLength(3);
		expect(s.theme).toBe('graphite');
	});

	it('无备份可救时才回落默认值（首次运行路径不变）', async () => {
		const mod = await realStore();
		mod.useSettingsStore.getState().hydrate();
		await settle();
		expect(mod.useSettingsStore.getState().profiles).toHaveLength(1);
	});

	it('主键可读时以主键为准，不被更富的备份顶掉', async () => {
		window.localStorage.setItem(KEY, settingsJson(2, 'graphite'));
		window.localStorage.setItem(BACKUP, settingsJson(9));
		const mod = await realStore();
		mod.useSettingsStore.getState().hydrate();
		await settle();
		expect(mod.useSettingsStore.getState().profiles).toHaveLength(2);
	});

	it('更穷的值写盘不得冲掉好备份', async () => {
		window.localStorage.setItem(KEY, settingsJson(4));
		window.localStorage.setItem(BACKUP, settingsJson(4));
		const mod = await realStore();
		const store = mod.useSettingsStore;
		store.getState().hydrate();
		await settle();
		expect(profileCountIn(window.localStorage.getItem(KEY))).toBe(4);

		// 模拟事故后半程：账号已丢光（只剩默认账号），此时任何一次写盘都不得
		// 把好备份也一起冲掉——否则下次启动就再没有可救的东西。
		store.setState({
			profiles: [
				{
					id: 'p_default',
					provider: 'deepseek',
					model: 'deepseek-v4-flash',
					apiKey: '',
					baseUrl: '',
				},
			],
		} as never);
		store.getState().update({});

		expect(profileCountIn(window.localStorage.getItem(KEY))).toBe(1);
		expect(profileCountIn(window.localStorage.getItem(BACKUP))).toBe(4);
	});
});
