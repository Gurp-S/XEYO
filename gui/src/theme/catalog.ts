/** 二十套黑白基调主题目录：语义色 ID + 明暗 scheme + 默认强调色。 */

export const THEME_IDS = [
	'paper',
	'pure',
	'platinum',
	'pearl',
	'letterpress',
	'sketch',
	'moon',
	'mist',
	'steel',
	'ivory',
	'void',
	'graphite',
	'darkroom',
	'woodcut',
	'grayscale',
	'basalt',
	'soot',
	'selenium',
	'velvet',
	'lead',
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
	{
		id: 'paper',
		label: '宣纸',
		scheme: 'light',
		defaultAccent: '#1c1b18',
		swatches: {paper: '#faf9f6', ink: '#1c1b18', accent: '#1c1b18'},
	},
	{
		id: 'pure',
		label: '极简白',
		scheme: 'light',
		defaultAccent: '#0a0a0a',
		swatches: {paper: '#ffffff', ink: '#0a0a0a', accent: '#0a0a0a'},
	},
	{
		id: 'platinum',
		label: '铂银',
		scheme: 'light',
		defaultAccent: '#2f353b',
		swatches: {paper: '#f6f7f8', ink: '#17191c', accent: '#2f353b'},
	},
	{
		id: 'pearl',
		label: '珍珠',
		scheme: 'light',
		defaultAccent: '#4a4a52',
		swatches: {paper: '#f5f5f6', ink: '#232326', accent: '#4a4a52'},
	},
	{
		id: 'letterpress',
		label: '铅印',
		scheme: 'light',
		defaultAccent: '#161513',
		swatches: {paper: '#f3f1ec', ink: '#161513', accent: '#161513'},
	},
	{
		id: 'sketch',
		label: '素描',
		scheme: 'light',
		defaultAccent: '#a83a32',
		swatches: {paper: '#f5f4f2', ink: '#1f1f1f', accent: '#a83a32'},
	},
	{
		id: 'moon',
		label: '月白',
		scheme: 'light',
		defaultAccent: '#3d4f5e',
		swatches: {paper: '#f5f7f8', ink: '#1b2026', accent: '#3d4f5e'},
	},
	{
		id: 'mist',
		label: '晨雾',
		scheme: 'light',
		defaultAccent: '#5a6167',
		swatches: {paper: '#f2f3f4', ink: '#2e3236', accent: '#5a6167'},
	},
	{
		id: 'steel',
		label: '青钢',
		scheme: 'light',
		defaultAccent: '#2e3d47',
		swatches: {paper: '#f3f5f6', ink: '#1a2126', accent: '#2e3d47'},
	},
	{
		id: 'ivory',
		label: '象牙',
		scheme: 'light',
		defaultAccent: '#2a2723',
		swatches: {paper: '#f7f5f0', ink: '#1e1c18', accent: '#2a2723'},
	},
	{
		id: 'void',
		label: '纯黑',
		scheme: 'dark',
		defaultAccent: '#f3f3f4',
		swatches: {paper: '#050506', ink: '#f3f3f4', accent: '#f3f3f4'},
	},
	{
		id: 'graphite',
		label: '石墨',
		scheme: 'dark',
		defaultAccent: '#d5d8dd',
		swatches: {paper: '#141518', ink: '#e9eaec', accent: '#d5d8dd'},
	},
	{
		id: 'darkroom',
		label: '暗房',
		scheme: 'dark',
		defaultAccent: '#c94f43',
		swatches: {paper: '#09090a', ink: '#ebebeb', accent: '#c94f43'},
	},
	{
		id: 'woodcut',
		label: '版画',
		scheme: 'dark',
		defaultAccent: '#ffffff',
		swatches: {paper: '#000000', ink: '#ffffff', accent: '#ffffff'},
	},
	{
		id: 'grayscale',
		label: '灰阶',
		scheme: 'dark',
		defaultAccent: '#b0b0b0',
		swatches: {paper: '#1a1a1a', ink: '#dcdcdc', accent: '#b0b0b0'},
	},
	{
		id: 'basalt',
		label: '玄岩',
		scheme: 'dark',
		defaultAccent: '#ccd2d9',
		swatches: {paper: '#0b0c0e', ink: '#e9ebee', accent: '#ccd2d9'},
	},
	{
		id: 'soot',
		label: '煤烟',
		scheme: 'dark',
		defaultAccent: '#e6e2d9',
		swatches: {paper: '#121110', ink: '#ecebe8', accent: '#e6e2d9'},
	},
	{
		id: 'selenium',
		label: '硒盐',
		scheme: 'dark',
		defaultAccent: '#ded2bd',
		swatches: {paper: '#141210', ink: '#eae6df', accent: '#ded2bd'},
	},
	{
		id: 'velvet',
		label: '黑绒',
		scheme: 'dark',
		defaultAccent: '#d6cfe0',
		swatches: {paper: '#0e0c10', ink: '#ece9f0', accent: '#d6cfe0'},
	},
	{
		id: 'lead',
		label: '铅灰',
		scheme: 'dark',
		defaultAccent: '#a9a9b0',
		swatches: {paper: '#212124', ink: '#e4e4e6', accent: '#a9a9b0'},
	},
] as const;

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
	return isThemeId(v) ? v : 'paper';
}

export function themeScheme(id: ThemeId): ThemeScheme {
	return getThemeMeta(id).scheme;
}

export function isDarkScheme(id: ThemeId): boolean {
	return themeScheme(id) === 'dark';
}
