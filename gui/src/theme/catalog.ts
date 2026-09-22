/** 六套黑白基调主题目录：语义色 ID + 明暗 scheme + 默认强调色。
 *
 *  2026-09-21 收敛：20 套 → 6 套。每套单独调校（灰阶可读性 + 强调色对比），
 *  而不是同一套灰阶换个色相。配色值与 styles/tokens.css 的 data-theme 块一一对应。
 */

export const THEME_IDS = [
	'paper',
	'ivory',
	'mist',
	'basalt',
	'graphite',
	'darkroom',
] as const;

export type ThemeId = (typeof THEME_IDS)[number];
export type ThemeScheme = 'light' | 'dark';

export type ThemeMeta = {
	id: ThemeId;
	label: string;
	scheme: ThemeScheme;
	/** 主题默认强调色（用户未自定义时） */
	defaultAccent: string;
	/** 色卡预览：纸面 / 墨色 / 强调 */
	swatches: {paper: string; ink: string; accent: string};
};

export const THEME_CATALOG: readonly ThemeMeta[] = [
	/* —— 浅色 —— */
	{
		id: 'paper',
		label: '霜白',
		scheme: 'light',
		defaultAccent: '#4f5dd8',
		swatches: {paper: '#f7f8fc', ink: '#1e2130', accent: '#4f5dd8'},
	},
	{
		id: 'ivory',
		label: '暖霜',
		scheme: 'light',
		defaultAccent: '#0f7d72',
		swatches: {paper: '#faf8f4', ink: '#23201a', accent: '#0f7d72'},
	},
	{
		id: 'mist',
		label: '雾蓝',
		scheme: 'light',
		defaultAccent: '#3f6fa8',
		swatches: {paper: '#f1f4f7', ink: '#1c2430', accent: '#3f6fa8'},
	},
	/* —— 深色 —— */
	{
		id: 'basalt',
		label: '墨紫',
		scheme: 'dark',
		defaultAccent: '#b79bff',
		swatches: {paper: '#100e18', ink: '#ece9f0', accent: '#b79bff'},
	},
	{
		id: 'graphite',
		label: '深空',
		scheme: 'dark',
		defaultAccent: '#9db0ff',
		swatches: {paper: '#0f1220', ink: '#e8ebf6', accent: '#9db0ff'},
	},
	{
		id: 'darkroom',
		label: '暗房',
		scheme: 'dark',
		defaultAccent: '#ff7a63',
		swatches: {paper: '#0a0a0b', ink: '#ededed', accent: '#ff7a63'},
	},
] as const;

/** 已下线主题 → 就近保留套。存档/斜杠命令/备份里出现的旧 ID 一律走这张表，
 *  而不是直接掉回默认档——用户选过的明暗与冷暖倾向要保住。 */
export const THEME_MIGRATION: Readonly<Record<string, ThemeId>> = {
	// 浅色：正白/暖白 → 宣纸或象牙；冷灰系 → 晨雾
	pure: 'paper',
	letterpress: 'ivory',
	sketch: 'ivory',
	platinum: 'mist',
	pearl: 'mist',
	moon: 'mist',
	steel: 'mist',
	// 深色：近黑 → 玄岩；中性/暖黑 → 石墨；红调 → 暗房
	void: 'basalt',
	woodcut: 'basalt',
	grayscale: 'graphite',
	lead: 'graphite',
	soot: 'graphite',
	selenium: 'graphite',
	velvet: 'graphite',
};

const THEME_BY_ID = Object.fromEntries(
	THEME_CATALOG.map(t => [t.id, t]),
) as Record<ThemeId, ThemeMeta>;

export function getThemeMeta(id: ThemeId): ThemeMeta {
	return THEME_BY_ID[id] ?? THEME_BY_ID.paper;
}

export function isThemeId(v: unknown): v is ThemeId {
	return typeof v === 'string' && (THEME_IDS as readonly string[]).includes(v);
}

export function normalizeThemeId(v: unknown): ThemeId {
	if (isThemeId(v)) return v;
	if (typeof v === 'string' && v in THEME_MIGRATION) return THEME_MIGRATION[v];
	return 'paper';
}

export function themeScheme(id: ThemeId): ThemeScheme {
	return getThemeMeta(id).scheme;
}

export function isDarkScheme(id: ThemeId): boolean {
	return themeScheme(id) === 'dark';
}
