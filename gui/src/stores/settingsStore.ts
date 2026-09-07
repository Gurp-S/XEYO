import {create} from 'zustand';
import {deleteKv, getKv, setKv} from '@/lib/db';
import {prefersReducedMotion} from '@/lib/prefersReducedMotion';
import {
	isDarkScheme,
	isThemeId,
	normalizeThemeId,
	themeScheme,
	type ThemeId,
} from '@/theme/catalog';

export type {ThemeId} from '@/theme/catalog';
import {isTestProvider} from '@/lib/localTestGate';

// 'local'/'fake' 仅本地测试 provider（localTestGate 管理，生产构建不可达）。
export type ProviderId = 'deepseek' | 'openai' | 'local' | 'fake';
export type RemoteChannel = 'filehelper' | 'ilink';
export type PermissionMode = 'always' | 'risk' | 'never';
export type OutputMode = 'lite' | 'full' | 'ultra';

/**
 * 面板布局与分割线（设置 → 外观）。
 * classic=现状胶囊缝；wireless=无线化纯留白；islands=圆角分岛；dotted=虚点呼吸线。
 * 仅视觉档位，CSS 按 html[data-pane-layout] 分发（styles/pane-layouts.css）。
 */
export type PaneLayout = 'classic' | 'wireless' | 'islands' | 'dotted';

export const PANE_LAYOUTS: readonly {id: PaneLayout; label: string; hint: string}[] = [
	{id: 'islands', label: '圆角分岛', hint: '三栏各自成卡，结构感最强（原方案4）'},
	{id: 'wireless', label: '无线化', hint: '无分割线，会话区变圆角岛（原方案1）'},
	{id: 'dotted', label: '虚点线', hint: '1px 点状虚线，视觉重量最低（原方案6）'},
	{id: 'classic', label: '经典', hint: '当前默认：圆角胶囊缝'},
];

export function normalizePaneLayout(v: unknown): PaneLayout {
	// 默认档 = 圆角分岛（islands）；与 DEFAULTS.paneLayout 保持一致。
	return v === 'wireless' || v === 'islands' || v === 'dotted' || v === 'classic'
		? v
		: 'islands';
}

export type ModelProfile = {
	id: string;
	provider: ProviderId;
	/** 当前激活模型（兼容字段，单值）。多模型时指向 models 中的某一个。 */
	model: string;
	apiKey: string;
	baseUrl: string;
	/** 供应商名称（展示用，例如 “DeepSeek 官方”）。 */
	name?: string;
	/** 账号备注（例如 “公司专用账号”）。 */
	note?: string;
	/** 官网链接（可选）。 */
	website?: string;
	/**
	 * 上下文窗口（token）。用户保存时以用户填写为准（不再被厂商 /models 覆盖）。
	 */
	contextLimit?: number;
	/**
	 * 最大输出 tokens（可选）。None = 不限制，不发送该字段。
	 */
	maxOutputTokens?: number;
	/**
	 * 该账号登记的模型集合（支持多模型）。旧版单模型数据迁移时会自动放入
	 * models[0] = {id: model, contextLimit, maxOutputTokens}。
	 */
	models?: ModelInput[];
};

/**
 * 单个模型的登记信息。多模型主要由「配置/展示」驱动，会话级 `model` 仍为单值
 * （激活模型），不要求按模型粒度并行调用。
 */
export type ModelInput = {
	id: string;
	/** 上下文窗口（token）。可选。 */
	contextLimit?: number;
	/** 最大输出 tokens。可选。 */
	maxOutputTokens?: number;
	inputType?: 'text' | 'image' | 'video';
	outputType?: 'text' | 'image';
	/** 该模型支持的思考等级集合（多选）；空/缺省 = 未限定。 */
	reasoningLevels?: ReasoningEffort[];
	/** 该模型的默认思考等级；空/缺省 = 用会话级 reasoningEffort。 */
	defaultReasoningEffort?: ReasoningEffort | '';
	/** @deprecated 旧单值；仅迁移兼容，运行时不再读取。 */
	reasoningEffort?: ReasoningEffort | '';
};

/** 思考等级（空字符串 = 自动/不指定）。 */
export type ReasoningEffort =
	| 'none'
	| 'minimal'
	| 'low'
	| 'medium'
	| 'high'
	| 'xhigh'
	| 'max'
	| 'ultra';

/** 全部可选思考等级，按展示顺序；供设置页/输入框遍历。 */
export const REASONING_EFFORTS: readonly ReasoningEffort[] = [
	'none',
	'minimal',
	'low',
	'medium',
	'high',
	'xhigh',
	'max',
	'ultra',
];

export type Settings = {
	provider: ProviderId;
	model: string;
	apiKey: string;
	baseUrl: string;
	thinking: 'disabled' | 'enabled';
	reasoningEffort: 'low' | 'high' | 'max' | '';
	/** L1.2：单次对话（submit）的 USD 上限（美元）；空 = 不限（后端可读 XEYO_MAX_BUDGET_USD）。 */
	maxBudgetUsd: string;
	/** 编辑审批模式：始终批准 / 仅风险（默认）/ 从不。 */
	permissionMode: PermissionMode;
	/** 输出精简：开启后本轮起在对话尾部（T_now）注入压缩铁律与模式段；不进 system，保住 KV 前缀。 */
	outputCompact: boolean;
	/** 输出精简模式；仅 outputCompact 开启时生效。 */
	outputMode: OutputMode;
	/** 写代码精简：开启后 T_now 注入实现体积铁律；与输出精简独立。 */
	codeCompact: boolean;
	/** 写代码精简模式；仅 codeCompact 开启时生效。 */
	codeMode: OutputMode;
	/**
	 * 上一轮思考回顾：开启后工具续写轮把上一轮推理结尾注入 T_now（弱模型防
	 * 重复思考的兜底）；强模型不建议。默认关；子代理不继承。
	 */
	reasoningTail: boolean;
	/** 可选自建 SearXNG 基址；空则 WebSearch 用 Bing/Mojeek。 */
	searxngUrl: string;
	/** 本地保存的多套厂商账号；当前对话使用 activeProfileId 对应的那套。 */
	profiles: ModelProfile[];
	activeProfileId: string;
	/** 微信远程通道：文件传输助手网页，或 ClawBot / iLink HTTP */
	remoteChannel: RemoteChannel;
	/** 外观主题 ID（见 theme/catalog）；明暗由 themeScheme 决定 */
	theme: ThemeId;
	/** @deprecated 兼容旧存储；运行时以 accentByTheme 为准 */
	accentColorLight: string;
	/** @deprecated 兼容旧存储；运行时以 accentByTheme 为准 */
	accentColorDark: string;
	/** 各主题独立自定义强调色；缺省则用该主题 CSS 默认 */
	accentByTheme: Partial<Record<ThemeId, string>>;
	/** 用户最近使用的强调色（新→旧，最多 8 个） */
	accentHistory: string[];
	/** data URL 或空字符串 — 存于 IndexedDB，而非 localStorage */
	bgImage: string;
	/** 0–100 图片层叠加不透明度 */
	bgOpacity: number;
	/** 0–40 px UI 面板背景模糊；图片本身也使用此值作为 CSS blur */
	bgBlur: number;
	/** 侧边栏宽度（px，读写时钳制） */
	sidebarWidth: number;
	/** 文件预览栏宽度 */
	previewWidth: number;
	/** 右侧文件树宽度 */
	explorerWidth: number;
	/**
	 * 流畅：输入/滚动/分割条跟屏幕刷新；Agent 事件每帧最多提交一次。
	 * 缺省为开。
	 */
	smoothness: boolean;
	/** 标题栏底部分割线；缺省为开。 */
	titleBarDivider: boolean;
	/**
	 * 面板布局与分割线档位（外观页可切）。缺省/非法 = islands（圆角分岛）。
	 * CSS 分发见 styles/pane-layouts.css。
	 */
	paneLayout: PaneLayout;
	/** 侧边栏开合动画使用“极平滑减速”（④ quintic-out）而非默认“柔和减速”（② expo-out）。 */
	paneEaseSilky: boolean;
	/**
	 * 气泡吸顶（Sticky）：开启后用户气泡滚近顶部被吸附、编辑气泡浮顶编辑；
	 * 关闭（默认）则气泡随滚动自然离开、编辑在当前消息原位展开。
	 */
	stickyBubbles: boolean;
	/** Context Pasture 总开关；缺失时默认开启以兼容旧配置。 */
	pastureEnabled: boolean;
	/** 仅保留极轻的氛围呼吸，关闭大幅动作。 */
	pastureReducedMotion: boolean;
	/** 暂停生态生命周期推进，但保留静态场景。 */
	pasturePaused: boolean;
	/** XeyoPet 独立桌宠总开关；缺失时默认开启。 */
	xeyoPetEnabled: boolean;
	/** 当前选中的 XeyoPet manifest id。 */
	xeyoPetId: string;
	/** 桌宠只保留首帧，尊重低动态偏好。 */
	xeyoPetReducedMotion: boolean;
	/**
	 * 回溯时使用整棵 Shadow Git 树恢复（较慢，可能触发 GUI 热更新）。
	 * 默认关闭：只恢复本轮 Agent 改过的文件。
	 */
	rewindFullTreeRestore: boolean;
	/** 回溯 blob GC：保留最近 N 个可回退检查点（null = 用后端默认 10）。 */
	rewindGcKeepRecent: number | null;
	/** 回溯 blob GC：单会话快照空间预算（字节；null = 用后端默认）。 */
	rewindGcMaxBytes: number | null;
	/**
	 * T32：显示「实验功能」入口（AgentMap 代码/架构地图等半成品收进实验菜单）。
	 * 默认关闭——半成品移出主界面 chrome，需在设置里显式开启。
	 */
	showExperimental: boolean;
};

export const SIDEBAR_WIDTH_MIN = 180;
export const SIDEBAR_WIDTH_MAX = 420;
export const SIDEBAR_WIDTH_DEFAULT = 248;
export const PANE_WIDTH_MIN = SIDEBAR_WIDTH_MIN;
export const PANE_WIDTH_MAX = SIDEBAR_WIDTH_MAX;
export const PREVIEW_WIDTH_DEFAULT = 360;
export const EXPLORER_WIDTH_DEFAULT = 248;

const STORAGE_KEY = 'xeyo-settings';
const OLD_STORAGE_KEY = 'xy-agent-settings';
const BG_KV_KEY = 'bgImage';

/** 解析设置里的可空整数（GC 保留数量 / 空间预算），非整数或空缺回 null。 */
function asIntOrNull(value: unknown): number | null {
	if (value === null || value === undefined || value === '') {
		return null;
	}
	const n = Number(value);
	return Number.isFinite(n) ? Math.trunc(n) : null;
}

const DEFAULTS: Settings = {
	provider: 'deepseek',
	model: 'deepseek-v4-flash',
	apiKey: '',
	baseUrl: '',
	thinking: 'disabled',
	reasoningEffort: '',
	maxBudgetUsd: '',
	permissionMode: 'risk',
	outputCompact: false,
	outputMode: 'lite',
	codeCompact: false,
	codeMode: 'lite',
	reasoningTail: false,
	searxngUrl: '',
	profiles: [],
	activeProfileId: '',
	theme: 'paper',
	accentColorLight: '',
	accentColorDark: '',
	accentByTheme: {},
	accentHistory: [],
	remoteChannel: 'ilink',
	bgImage: '',
	/** 壁纸清晰度 0–100（越高 = 遮罩越薄）。 */
	bgOpacity: 70,
	bgBlur: 12,
	sidebarWidth: SIDEBAR_WIDTH_DEFAULT,
	previewWidth: PREVIEW_WIDTH_DEFAULT,
		explorerWidth: EXPLORER_WIDTH_DEFAULT,
			smoothness: true,
			titleBarDivider: true,
			paneLayout: 'islands',
			paneEaseSilky: false,
			stickyBubbles: false,
			pastureEnabled: true,
		pastureReducedMotion: false,
		pasturePaused: false,
		xeyoPetEnabled: false,
		xeyoPetId: 'xeyo-sea-sprite-plus',
		xeyoPetReducedMotion: false,
		rewindFullTreeRestore: false,
		rewindGcKeepRecent: null,
		rewindGcMaxBytes: null,
		showExperimental: false,
};

let themeFlashTimer: ReturnType<typeof setTimeout> | null = null;

export function applyDocumentTheme(theme: ThemeId) {
	const el = document.documentElement;
	el.dataset.theme = theme;
	el.dataset.scheme = themeScheme(theme);
	el.dataset.themeFlash = '1';
	if (themeFlashTimer !== null) {
		clearTimeout(themeFlashTimer);
	}
	themeFlashTimer = setTimeout(() => {
		themeFlashTimer = null;
		if (el.dataset.themeFlash === '1') {
			delete el.dataset.themeFlash;
		}
	}, 320);
}

/** 外观设置里的系统推荐强调色（配合宣纸 / 碳黑主题调低饱和）。 */
export const ACCENT_RECOMMENDATIONS: {name: string; color: string}[] = [
	{name: '青瓷 · 默认', color: '#0e6f68'},
	{name: '松石灰绿', color: '#57796f'},
	{name: '香槟灰金', color: '#75684e'},
	{name: '陶赭', color: '#8a6f64'},
	{name: '黛蓝', color: '#5b7fa5'},
	{name: '灰薄荷', color: '#8bb0a5'},
];

const ACCENT_HISTORY_MAX = 8;

/** 归一化为 #rrggbb 小写；非法返回 ''。 */
export function normalizeHexColor(v: unknown): string {
	if (typeof v !== 'string') {
		return '';
	}
	const s = v.trim().toLowerCase();
	const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(s);
	if (!m) {
		return '';
	}
	const hex = s.slice(1);
	return `#${hex.length === 3 ? hex.split('').map(c => c + c).join('') : hex}`;
}

function hexToRgb(hex: string): [number, number, number] {
	const h = hex.slice(1);
	return [
		parseInt(h.slice(0, 2), 16),
		parseInt(h.slice(2, 4), 16),
		parseInt(h.slice(4, 6), 16),
	];
}

/** 相对亮度 > 0.62 视为浅色，强调色上要用深色文字。 */
function isLightAccent(hex: string): boolean {
	const [r, g, b] = hexToRgb(hex).map(v => {
		const c = v / 255;
		return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.62;
}

/**
 * 把当前主题的自定义强调色写到 documentElement 内联样式。
 * 空字符串 = 移除内联覆盖，回到该主题 CSS 默认色。
 */
export function applyDocumentAccent(accent: string, _theme?: ThemeId) {
	const el = document.documentElement;
	const c = normalizeHexColor(accent);
	if (!c) {
		['--xy-accent', '--xy-accent-hover', '--xy-accent-soft', '--xy-on-accent']
			.forEach(p => el.style.removeProperty(p));
		return;
	}
	el.style.setProperty('--xy-accent', c);
	el.style.setProperty('--xy-accent-hover', `color-mix(in oklch, ${c} 82%, black)`);
	el.style.setProperty('--xy-accent-soft', `color-mix(in oklch, ${c} 14%, transparent)`);
	el.style.setProperty('--xy-on-accent', isLightAccent(c) ? '#1c1a17' : '#ffffff');
}

/** 读取某主题的自定义强调色（空 = 用 CSS 默认）。 */
export function accentForThemeId(
	accentByTheme: Partial<Record<ThemeId, string>> | undefined,
	theme: ThemeId,
): string {
	return normalizeHexColor(accentByTheme?.[theme] ?? '');
}

/** 缺省 / 非 false 都视为开；系统「减少动态」时强制关流畅。 */
export function isSmoothnessOn(value?: unknown): boolean {
	if (value === false) {
		return false;
	}
	if (prefersReducedMotion()) {
		return false;
	}
	return true;
}

export function applyDocumentSmoothness(on: boolean) {
	const effective = isSmoothnessOn(on);
	document.documentElement.dataset.smoothness = effective ? 'on' : 'off';
}

/** 气泡吸顶总开关 → html[data-xy-sticky-bubbles]；CSS 据此放开/启用原生 sticky。 */
export function applyDocumentStickyBubbles(on: boolean) {
	document.documentElement.dataset.xyStickyBubbles = on ? 'on' : 'off';
}

/** 面板布局档位 → html[data-pane-layout]；CSS 据此分发分割线样式。 */
export function applyDocumentPaneLayout(layout: PaneLayout) {
	document.documentElement.dataset.paneLayout = normalizePaneLayout(layout);
}

/** 监听系统减少动态偏好，同步 data-smoothness。 */
export function bindReducedMotionToSmoothness(
	getSmoothness: () => boolean,
): () => void {
	if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
		return () => undefined;
	}
	const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
	const sync = () => {
		applyDocumentSmoothness(getSmoothness());
	};
	sync();
	mq.addEventListener('change', sync);
	return () => mq.removeEventListener('change', sync);
}

/** 侧边栏开合缓动：默认柔和减速(② expo-out)，true = 极平滑减速(④ quintic-out)。 */
export function applyDocumentPaneEase(silky: boolean) {
	document.documentElement.dataset.paneEase = silky ? 'silky' : 'soft';
}

function normalizeTheme(v: unknown): ThemeId {
	return normalizeThemeId(v);
}

function normalizeAccentHistory(v: unknown): string[] {
	if (!Array.isArray(v)) {
		return [];
	}
	const out: string[] = [];
	for (const item of v) {
		const c = normalizeHexColor(item);
		if (c && !out.includes(c)) {
			out.push(c);
		}
	}
	return out.slice(0, ACCENT_HISTORY_MAX);
}

/** 解析明暗强调色；兼容旧版单一 accentColor 字段（同时迁移到明暗）。 */
function parseAccentPair(parsed: {
	accentColorLight?: unknown;
	accentColorDark?: unknown;
	accentColor?: unknown;
}): {accentColorLight: string; accentColorDark: string} {
	const light = normalizeHexColor(parsed.accentColorLight);
	const dark = normalizeHexColor(parsed.accentColorDark);
	if (light || dark) {
		return {accentColorLight: light, accentColorDark: dark};
	}
	const legacy = normalizeHexColor(parsed.accentColor);
	return {accentColorLight: legacy, accentColorDark: legacy};
}

/** 各主题独立强调色；旧版 light/dark 仅迁移到对应 ID，不污染其它主题。 */
function parseAccentByTheme(parsed: {
	accentByTheme?: unknown;
	accentColorLight?: unknown;
	accentColorDark?: unknown;
	accentColor?: unknown;
}): Partial<Record<ThemeId, string>> {
	const out: Partial<Record<ThemeId, string>> = {};
	const raw = parsed.accentByTheme;
	if (raw && typeof raw === 'object') {
		const map = raw as Record<string, unknown>;
		for (const id of Object.keys(map)) {
			if (!isThemeId(id)) {
				continue;
			}
			const c = normalizeHexColor(map[id]);
			if (c) {
				out[id] = c;
			}
		}
	}
	const pair = parseAccentPair(parsed);
	// 旧单双主题字段按 scheme 默认主题落位：light→paper，dark→graphite
	if (pair.accentColorLight && !out.paper) {
		out.paper = pair.accentColorLight;
	}
	if (pair.accentColorDark && !out.graphite) {
		out.graphite = pair.accentColorDark;
	}
	return out;
}

export function normalizeRemoteChannel(v: unknown): RemoteChannel {
	return v === 'filehelper' ? 'filehelper' : 'ilink';
}

export function normalizePermissionMode(v: unknown): PermissionMode {
	return v === 'always' || v === 'never' ? v : 'risk';
}

export function normalizeOutputMode(v: unknown): OutputMode {
	return v === 'full' || v === 'ultra' ? v : 'lite';
}

function clampPaneWidth(n: number, fallback: number): number {
	if (!Number.isFinite(n)) {
		return fallback;
	}
	return Math.min(PANE_WIDTH_MAX, Math.max(PANE_WIDTH_MIN, Math.round(n)));
}

function clampSidebarWidth(n: number): number {
	return clampPaneWidth(n, SIDEBAR_WIDTH_DEFAULT);
}

function newProfileId(): string {
	return `p_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export function isProviderId(v: unknown): v is ProviderId {
	// 'local'/'fake' 仅为本地测试 provider，受 localTestGate 管理（T25c）。
	return v === 'deepseek' || v === 'openai' || isTestProvider(v as string);
}

export function keyFingerprint(apiKey: string): string {
	const s = (apiKey || '').replace(/[^a-zA-Z0-9]/g, '');
	if (s.length < 4) {
		return '';
	}
	return `…${s.slice(-4)}`;
}

export function modelLabel(modelId: string): string {
	return modelId || '';
}

/** 把可空数值归一化为正整数；非法/空/<=0 返回 undefined。 */
function toPositiveInt(v: unknown): number | undefined {
	if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) {
		return undefined;
	}
	return Math.floor(v);
}

function normalizeModelInput(raw: unknown): ModelInput | null {
	if (!raw || typeof raw !== 'object') {
		return null;
	}
	const row = raw as Partial<ModelInput>;
	const id = typeof row.id === 'string' ? row.id.trim() : '';
	if (!id) {
		return null;
	}
	const out: ModelInput = {id};
	const contextLimit = toPositiveInt(row.contextLimit);
	if (contextLimit != null) {
		out.contextLimit = contextLimit;
	}
	const maxOutputTokens = toPositiveInt(row.maxOutputTokens);
	if (maxOutputTokens != null) {
		out.maxOutputTokens = maxOutputTokens;
	}
	if (row.inputType === 'text' || row.inputType === 'image' || row.inputType === 'video') {
		out.inputType = row.inputType;
	}
	if (row.outputType === 'text' || row.outputType === 'image') {
		out.outputType = row.outputType;
	}
	// 新字段：reasoningLevels（多选）+ defaultReasoningEffort（默认等级）。
	if (Array.isArray(row.reasoningLevels)) {
		const set = row.reasoningLevels.filter(isReasoningEffort);
		if (set.length > 0) {
			out.reasoningLevels = set;
		}
	}
	if (isReasoningEffort(row.defaultReasoningEffort)) {
		out.defaultReasoningEffort = row.defaultReasoningEffort;
	} else if (isReasoningEffort(row.reasoningEffort)) {
		// 旧单值迁移为默认等级。
		out.defaultReasoningEffort = row.reasoningEffort;
	}
	return out;
}

/** 思考等级白名单校验（空串不算，未设置返回 false）。 */
function isReasoningEffort(v: unknown): v is ReasoningEffort {
	return (
		typeof v === 'string' &&
		(v === 'none' ||
			v === 'minimal' ||
			v === 'low' ||
			v === 'medium' ||
			v === 'high' ||
			v === 'xhigh' ||
			v === 'max' ||
			v === 'ultra')
	);
}

/**
 * 归一化模型数组。给定合法 models 数组时原样使用；否则回退到单个模型
 * （兼容旧数据：model + contextLimit/maxOutputTokens 迁移为 models[0]）。
 */
function normalizeModels(
	raw: unknown,
	fallback: {model: string; contextLimit?: number; maxOutputTokens?: number},
): ModelInput[] {
	if (Array.isArray(raw)) {
		const list = raw
			.map(normalizeModelInput)
			.filter((m): m is ModelInput => m !== null);
		if (list.length > 0) {
			return list;
		}
	}
	const entry: ModelInput = {id: fallback.model};
	if (fallback.contextLimit != null) {
		entry.contextLimit = fallback.contextLimit;
	}
	if (fallback.maxOutputTokens != null) {
		entry.maxOutputTokens = fallback.maxOutputTokens;
	}
	return [entry];
}

/** 返回 profile 登记的全部模型 id；无 models 数组时回退到 [model]。 */
export function profileModelIds(profile: ModelProfile): string[] {
	if (Array.isArray(profile.models) && profile.models.length > 0) {
		return profile.models.map(m => m.id).filter(Boolean);
	}
	return profile.model ? [profile.model] : [];
}

function normalizeProfile(raw: unknown): ModelProfile | null {
	if (!raw || typeof raw !== 'object') {
		return null;
	}
	const row = raw as Partial<ModelProfile>;
	const provider: ProviderId = isProviderId(row.provider)
		? row.provider
		: 'deepseek';
	const model =
		typeof row.model === 'string' && row.model.trim()
			? row.model.trim()
			: 'deepseek-v4-flash';
	const id =
		typeof row.id === 'string' && row.id.trim()
			? row.id.trim()
			: newProfileId();
	const contextLimit = toPositiveInt(row.contextLimit);
	const maxOutputTokens = toPositiveInt(row.maxOutputTokens);
	const models = normalizeModels(row.models, {
		model,
		contextLimit,
		maxOutputTokens,
	});
	return {
		id,
		provider,
		model,
		apiKey: typeof row.apiKey === 'string' ? row.apiKey : '',
		baseUrl: typeof row.baseUrl === 'string' ? row.baseUrl : '',
		name: typeof row.name === 'string' ? row.name : undefined,
		note: typeof row.note === 'string' ? row.note : undefined,
		website: typeof row.website === 'string' ? row.website : undefined,
		contextLimit,
		maxOutputTokens,
		...((models.length ? {models} : {}) as {models?: ModelInput[]}),
	};
}

function seedProfiles(parsed: {
	provider: ProviderId;
	model: string;
	apiKey: string;
	baseUrl: string;
	profiles?: unknown;
	activeProfileId?: unknown;
}): {profiles: ModelProfile[]; activeProfileId: string} {
	const list = Array.isArray(parsed.profiles)
		? parsed.profiles.map(normalizeProfile).filter((p): p is ModelProfile => p !== null)
		: [];
	if (list.length > 0) {
		const want =
			typeof parsed.activeProfileId === 'string' ? parsed.activeProfileId : '';
		const active = list.some(p => p.id === want) ? want : list[0].id;
		return {profiles: list, activeProfileId: active};
	}
	const id = 'p_default';
	return {
		profiles: [
			{
				id,
				provider: parsed.provider,
				model: parsed.model,
						apiKey: parsed.apiKey,
						baseUrl: parsed.baseUrl,
						name: '',
						note: '',
						website: '',
						models: normalizeModels(undefined, {model: parsed.model}),
					},
		],
		activeProfileId: id,
	};
}

function applyActiveProfile(settings: Settings, profile: ModelProfile): Settings {
	return {
		...settings,
		activeProfileId: profile.id,
		provider: profile.provider,
		model: profile.model,
		apiKey: profile.apiKey,
		baseUrl: profile.baseUrl,
	};
}

function syncActiveIntoProfiles(settings: Settings): Settings {
	if (!settings.profiles.length) {
		return settings;
	}
	const id = settings.activeProfileId || settings.profiles[0].id;
	return {
		...settings,
		activeProfileId: id,
		profiles: settings.profiles.map(p =>
			p.id === id
				? {
						...p,
						provider: settings.provider,
						model: settings.model,
						apiKey: settings.apiKey,
						baseUrl: settings.baseUrl,
					}
				: p,
		),
	};
}

type PersistedLite = Omit<Settings, 'bgImage'>;

function loadLite(): PersistedLite {
	const fallback = (): PersistedLite => {
		const {bgImage: _b, ...lite} = DEFAULTS;
		const seeded = seedProfiles(lite);
		const active = seeded.profiles[0];
		return {
			...lite,
			...seeded,
			provider: active.provider,
			model: active.model,
			apiKey: active.apiKey,
			baseUrl: active.baseUrl,
		};
	};
	try {
		let raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) {
			raw = localStorage.getItem(OLD_STORAGE_KEY);
			if (raw) {
				localStorage.setItem(STORAGE_KEY, raw);
			}
		}
		if (!raw) {
			return fallback();
		}
		const parsed = {...DEFAULTS, ...JSON.parse(raw)} as Settings;
		const seeded = seedProfiles(parsed);
		const active =
			seeded.profiles.find(p => p.id === seeded.activeProfileId) ??
			seeded.profiles[0];
		return {
			provider: active.provider,
			model: active.model,
			apiKey: active.apiKey,
			baseUrl: active.baseUrl,
			thinking:
				parsed.thinking === 'enabled' ? 'enabled' : 'disabled',
			reasoningEffort:
				parsed.reasoningEffort === 'low' ||
				parsed.reasoningEffort === 'high' ||
				parsed.reasoningEffort === 'max'
					? parsed.reasoningEffort
					: '',
			maxBudgetUsd:
				typeof parsed.maxBudgetUsd === 'string'
					? parsed.maxBudgetUsd
					: '',
			permissionMode: normalizePermissionMode(parsed.permissionMode),
			outputCompact: parsed.outputCompact === true,
			outputMode: normalizeOutputMode(parsed.outputMode),
			codeCompact: parsed.codeCompact === true,
			codeMode: normalizeOutputMode(parsed.codeMode),
			reasoningTail: parsed.reasoningTail === true,
			searxngUrl:
				typeof parsed.searxngUrl === 'string' ? parsed.searxngUrl.trim() : '',
			profiles: seeded.profiles,
			activeProfileId: active.id,
			theme: normalizeTheme(parsed.theme),
			...parseAccentPair(parsed),
			accentByTheme: parseAccentByTheme(parsed),
			accentHistory: normalizeAccentHistory(parsed.accentHistory),
			remoteChannel: normalizeRemoteChannel(parsed.remoteChannel),
			bgOpacity: parsed.bgOpacity,
			bgBlur: parsed.bgBlur,
			sidebarWidth: clampSidebarWidth(parsed.sidebarWidth),
			previewWidth: clampPaneWidth(
				parsed.previewWidth,
				PREVIEW_WIDTH_DEFAULT,
			),
			explorerWidth: clampPaneWidth(
				parsed.explorerWidth,
				EXPLORER_WIDTH_DEFAULT,
			),
				smoothness: parsed.smoothness === false ? false : true,
				titleBarDivider: parsed.titleBarDivider === false ? false : true,
				paneLayout: normalizePaneLayout(parsed.paneLayout),
					paneEaseSilky: parsed.paneEaseSilky === true,
					stickyBubbles: parsed.stickyBubbles === true,
					pastureEnabled: parsed.pastureEnabled !== false,
					pastureReducedMotion: parsed.pastureReducedMotion === true,
					pasturePaused: parsed.pasturePaused === true,
				xeyoPetEnabled: parsed.xeyoPetEnabled === true,
				xeyoPetId:
					typeof parsed.xeyoPetId === 'string' && parsed.xeyoPetId.trim()
						? parsed.xeyoPetId.trim()
						: DEFAULTS.xeyoPetId,
				xeyoPetReducedMotion: parsed.xeyoPetReducedMotion === true,
				rewindFullTreeRestore: parsed.rewindFullTreeRestore === true,
				rewindGcKeepRecent: asIntOrNull(parsed.rewindGcKeepRecent),
				rewindGcMaxBytes: asIntOrNull(parsed.rewindGcMaxBytes),
				showExperimental: parsed.showExperimental === true,
				};
	} catch {
		return fallback();
	}
}

const PERSIST_DEBOUNCE_MS = 250;
let persistTimer: ReturnType<typeof setTimeout> | null = null;

function cancelPendingPersist() {
	if (persistTimer !== null) {
		clearTimeout(persistTimer);
		persistTimer = null;
	}
}

function writePersistLite(settings: Settings) {
	const lite: PersistedLite = {
		provider: settings.provider,
		model: settings.model,
		apiKey: settings.apiKey,
		baseUrl: settings.baseUrl,
		thinking: settings.thinking,
		reasoningEffort: settings.reasoningEffort,
		maxBudgetUsd: settings.maxBudgetUsd,
		permissionMode: settings.permissionMode,
		outputCompact: settings.outputCompact === true,
		outputMode: normalizeOutputMode(settings.outputMode),
		codeCompact: settings.codeCompact === true,
		codeMode: normalizeOutputMode(settings.codeMode),
		reasoningTail: settings.reasoningTail === true,
		searxngUrl: settings.searxngUrl ?? '',
		profiles: settings.profiles,
		activeProfileId: settings.activeProfileId,
		theme: settings.theme,
		accentColorLight: settings.accentByTheme?.paper ?? settings.accentColorLight ?? '',
		accentColorDark: settings.accentByTheme?.graphite ?? settings.accentColorDark ?? '',
		accentByTheme: settings.accentByTheme ?? {},
		accentHistory: settings.accentHistory ?? [],
		remoteChannel: settings.remoteChannel,
		bgOpacity: settings.bgOpacity,
		bgBlur: settings.bgBlur,
		sidebarWidth: settings.sidebarWidth,
		previewWidth: settings.previewWidth,
		explorerWidth: settings.explorerWidth,
			smoothness: settings.smoothness !== false,
			titleBarDivider: settings.titleBarDivider !== false,
			paneLayout: normalizePaneLayout(settings.paneLayout),
			paneEaseSilky: settings.paneEaseSilky === true,
			stickyBubbles: settings.stickyBubbles === true,
			pastureEnabled: settings.pastureEnabled !== false,
			pastureReducedMotion: settings.pastureReducedMotion === true,
			pasturePaused: settings.pasturePaused === true,
			xeyoPetEnabled: settings.xeyoPetEnabled === true,
			xeyoPetId: settings.xeyoPetId || DEFAULTS.xeyoPetId,
			xeyoPetReducedMotion: settings.xeyoPetReducedMotion === true,
			rewindFullTreeRestore: settings.rewindFullTreeRestore === true,
			rewindGcKeepRecent: asIntOrNull(settings.rewindGcKeepRecent),
			rewindGcMaxBytes: asIntOrNull(settings.rewindGcMaxBytes),
			showExperimental: settings.showExperimental === true,
		};
	localStorage.setItem(STORAGE_KEY, JSON.stringify(lite));
}

function persistLite(settings: Settings) {
	cancelPendingPersist();
	writePersistLite(settings);
}

function persistLiteTrailing() {
	cancelPendingPersist();
	persistTimer = setTimeout(() => {
		persistTimer = null;
		writePersistLite(useSettingsStore.getState());
	}, PERSIST_DEBOUNCE_MS);
}

export function flushPersist() {
	if (persistTimer === null) {
		return;
	}
	cancelPendingPersist();
	writePersistLite(useSettingsStore.getState());
}

if (typeof window !== 'undefined') {
	window.addEventListener('pagehide', flushPersist);
	document.addEventListener('visibilitychange', () => {
		if (document.visibilityState === 'hidden') {
			flushPersist();
		}
	});
}

export type SettingsTab =
	| 'appearance'
	| 'accounts'
	| 'rewind'
	| 'pet'
	| 'remote';

type SettingsState = Settings & {
	hydrated: boolean;
	/** 共享设置弹窗（ChatHeader + 无密钥 CTA）。 */
	settingsModalOpen: boolean;
	/** 打开设置时落到的页签。 */
	settingsInitialTab: SettingsTab;
	hydrate: () => void;
	hydrateAsync: () => Promise<void>;
	update: (patch: Partial<Settings>) => void;
	selectProfile: (id: string) => void;
	addProfile: (partial?: Partial<Omit<ModelProfile, 'id'>>) => string;
	updateProfile: (id: string, partial: Partial<Omit<ModelProfile, 'id'>>) => void;
	removeProfile: (id: string) => void;
	resolvedBaseUrl: () => string;
	openSettings: (tab?: SettingsTab) => void;
	closeSettings: () => void;
};

export const PROVIDER_DEFAULT_URL: Record<ProviderId, string> = {
	deepseek: 'https://api.deepseek.com/v1',
	openai: 'https://api.openai.com/v1',
	// 本地 llama.cpp（仅 localTestGate 开启时可选）。
	local: 'http://localhost:8080/v1',
	// HTTP 全栈测试假模型（仅 localTestGate 开启时可选）。
	fake: '',
};

export const PROVIDER_LABEL: Record<ProviderId, string> = {
	deepseek: 'DeepSeek',
	openai: 'OpenAI',
	// 仅 localTestGate 开启时可选（T25c）。
	local: '本地模型',
	fake: 'Fake（测试）',
};

export const MODEL_OPTIONS: {provider: ProviderId; id: string; label: string}[] =
	[];

/** @deprecated 模型列表以厂商 GET /models 为准 */

export const useSettingsStore = create<SettingsState>((set, get) => ({
	...DEFAULTS,
	hydrated: false,
	settingsModalOpen: false,
	settingsInitialTab: 'appearance',
	hydrate() {
		const lite = loadLite();
		applyDocumentTheme(lite.theme);
		applyDocumentAccent(accentForThemeId(lite.accentByTheme, lite.theme));
		applyDocumentSmoothness(lite.smoothness !== false);
		applyDocumentPaneEase(lite.paneEaseSilky === true);
		applyDocumentStickyBubbles(lite.stickyBubbles === true);
		applyDocumentPaneLayout(lite.paneLayout);
		set({...lite, hydrated: false});
		void get().hydrateAsync();
	},
	async hydrateAsync() {
		const lite = loadLite();
		let bgImage = '';
		try {
			bgImage = (await getKv(BG_KV_KEY)) ?? '';
		} catch {
			bgImage = '';
		}

		// 一次性迁移：旧版本将 bgImage 存在 localStorage JSON 中
		if (!bgImage) {
			try {
				const raw = localStorage.getItem(STORAGE_KEY);
				if (raw) {
					const parsed = JSON.parse(raw) as {bgImage?: string};
					if (parsed.bgImage) {
						bgImage = parsed.bgImage;
						await setKv(BG_KV_KEY, bgImage);
						persistLite({...DEFAULTS, ...lite, bgImage: ''});
					}
				}
			} catch {
				/* 忽略 */
			}
		}

		applyDocumentTheme(lite.theme);
		applyDocumentAccent(accentForThemeId(lite.accentByTheme, lite.theme));
		applyDocumentSmoothness(lite.smoothness !== false);
		applyDocumentPaneEase(lite.paneEaseSilky === true);
		applyDocumentStickyBubbles(lite.stickyBubbles === true);
		applyDocumentPaneLayout(lite.paneLayout);
		const next = {...lite, bgImage, hydrated: true};
		persistLite(next);
		set(next);
	},
	update(patch) {
		const cur = get();
		let next: Settings = {
			provider: cur.provider,
			model: cur.model,
			apiKey: cur.apiKey,
			baseUrl: cur.baseUrl,
			thinking: cur.thinking,
			reasoningEffort: cur.reasoningEffort,
			maxBudgetUsd: cur.maxBudgetUsd ?? '',
			permissionMode: cur.permissionMode ?? DEFAULTS.permissionMode,
			outputCompact: cur.outputCompact === true,
			outputMode: normalizeOutputMode(cur.outputMode),
			codeCompact: cur.codeCompact === true,
			codeMode: normalizeOutputMode(cur.codeMode),
			reasoningTail: cur.reasoningTail === true,
			searxngUrl: cur.searxngUrl ?? '',
			profiles: cur.profiles,
			activeProfileId: cur.activeProfileId,
			theme: cur.theme,
			accentColorLight: cur.accentColorLight ?? '',
			accentColorDark: cur.accentColorDark ?? '',
			accentByTheme: {...(cur.accentByTheme ?? {})},
			accentHistory: cur.accentHistory ?? [],
			remoteChannel: cur.remoteChannel,
			bgImage: cur.bgImage,
			bgOpacity: cur.bgOpacity,
			bgBlur: cur.bgBlur,
			sidebarWidth: cur.sidebarWidth ?? SIDEBAR_WIDTH_DEFAULT,
			previewWidth: cur.previewWidth ?? PREVIEW_WIDTH_DEFAULT,
			explorerWidth: cur.explorerWidth ?? EXPLORER_WIDTH_DEFAULT,
				smoothness: cur.smoothness !== false,
				titleBarDivider: cur.titleBarDivider !== false,
				paneLayout: normalizePaneLayout(cur.paneLayout),
					paneEaseSilky: cur.paneEaseSilky === true,
					stickyBubbles: cur.stickyBubbles === true,
					pastureEnabled: cur.pastureEnabled !== false,
					pastureReducedMotion: cur.pastureReducedMotion === true,
					pasturePaused: cur.pasturePaused === true,
				xeyoPetEnabled: cur.xeyoPetEnabled === true,
				xeyoPetId: cur.xeyoPetId || DEFAULTS.xeyoPetId,
				xeyoPetReducedMotion: cur.xeyoPetReducedMotion === true,
				rewindFullTreeRestore: cur.rewindFullTreeRestore === true,
				rewindGcKeepRecent: asIntOrNull(cur.rewindGcKeepRecent),
				rewindGcMaxBytes: asIntOrNull(cur.rewindGcMaxBytes),
				showExperimental: cur.showExperimental === true,
					...patch,
		};
		if (patch.rewindFullTreeRestore !== undefined) {
			next.rewindFullTreeRestore = patch.rewindFullTreeRestore === true;
		}
		if (patch.rewindGcKeepRecent !== undefined) {
			next.rewindGcKeepRecent = asIntOrNull(patch.rewindGcKeepRecent);
		}
		if (patch.rewindGcMaxBytes !== undefined) {
			next.rewindGcMaxBytes = asIntOrNull(patch.rewindGcMaxBytes);
		}
		if (patch.sidebarWidth !== undefined) {
			next.sidebarWidth = clampSidebarWidth(patch.sidebarWidth);
		}
		if (patch.previewWidth !== undefined) {
			next.previewWidth = clampPaneWidth(
				patch.previewWidth,
				PREVIEW_WIDTH_DEFAULT,
			);
		}
		if (patch.explorerWidth !== undefined) {
			next.explorerWidth = clampPaneWidth(
				patch.explorerWidth,
				EXPLORER_WIDTH_DEFAULT,
			);
		}
		if (patch.theme !== undefined) {
			next.theme = normalizeTheme(patch.theme);
			applyDocumentTheme(next.theme);
		}
		if (patch.accentByTheme !== undefined) {
			const merged: Partial<Record<ThemeId, string>> = {};
			for (const [id, raw] of Object.entries(patch.accentByTheme)) {
				if (!isThemeId(id)) {
					continue;
				}
				const c = normalizeHexColor(raw);
				if (c) {
					merged[id] = c;
				}
			}
			// 与上一版对比，找出新写入的色加入历史
			const prev = next.accentByTheme ?? {};
			for (const [id, c] of Object.entries(merged)) {
				if (c && prev[id as ThemeId] !== c) {
					next.accentHistory = [
						c,
						...(next.accentHistory ?? []).filter(h => h !== c),
					].slice(0, ACCENT_HISTORY_MAX);
				}
			}
			next.accentByTheme = merged;
			next.accentColorLight = isDarkScheme(next.theme) ? '' : merged[next.theme] ?? '';
			next.accentColorDark = isDarkScheme(next.theme) ? merged[next.theme] ?? '' : '';
		} else if (
			patch.accentColorLight !== undefined ||
			patch.accentColorDark !== undefined
		) {
			// 旧 API：写入「当前主题」槽位，不再污染同 scheme 其它主题
			const merged = {...(next.accentByTheme ?? {})};
			const raw = isDarkScheme(next.theme)
				? patch.accentColorDark
				: patch.accentColorLight;
			if (raw !== undefined) {
				const c = normalizeHexColor(raw);
				if (c) {
					merged[next.theme] = c;
					next.accentHistory = [
						c,
						...(next.accentHistory ?? []).filter(h => h !== c),
					].slice(0, ACCENT_HISTORY_MAX);
				} else {
					delete merged[next.theme];
				}
			}
			next.accentByTheme = merged;
			next.accentColorLight = isDarkScheme(next.theme) ? '' : merged[next.theme] ?? '';
			next.accentColorDark = isDarkScheme(next.theme) ? merged[next.theme] ?? '' : '';
		}
		if (
			patch.theme !== undefined ||
			patch.accentByTheme !== undefined ||
			patch.accentColorLight !== undefined ||
			patch.accentColorDark !== undefined
		) {
			applyDocumentAccent(accentForThemeId(next.accentByTheme, next.theme));
		}
		if (patch.smoothness !== undefined) {
			next.smoothness = patch.smoothness !== false;
			applyDocumentSmoothness(next.smoothness);
		}
		if (patch.titleBarDivider !== undefined) {
			next.titleBarDivider = patch.titleBarDivider !== false;
		}
		if (patch.paneLayout !== undefined) {
			next.paneLayout = normalizePaneLayout(patch.paneLayout);
			applyDocumentPaneLayout(next.paneLayout);
		}
		if (patch.paneEaseSilky !== undefined) {
			next.paneEaseSilky = patch.paneEaseSilky === true;
			applyDocumentPaneEase(next.paneEaseSilky);
		}
		if (patch.stickyBubbles !== undefined) {
			next.stickyBubbles = patch.stickyBubbles === true;
			applyDocumentStickyBubbles(next.stickyBubbles);
		}
		if (patch.remoteChannel !== undefined) {
			next.remoteChannel = normalizeRemoteChannel(patch.remoteChannel);
		}
		if (patch.profiles !== undefined) {
			next.profiles = patch.profiles
				.map(normalizeProfile)
				.filter((p): p is ModelProfile => p !== null);
		}
		if (!next.profiles.length) {
			const seeded = seedProfiles(next);
			next = applyActiveProfile({...next, ...seeded}, seeded.profiles[0]);
		} else if (
			patch.provider !== undefined ||
			patch.model !== undefined ||
			patch.apiKey !== undefined ||
			patch.baseUrl !== undefined
		) {
			next = syncActiveIntoProfiles(next);
		}
		const patchKeys = Object.keys(patch);
		const widthOnlyPatch =
			patchKeys.length > 0 &&
			patchKeys.every(
				k =>
					k === 'sidebarWidth' ||
					k === 'previewWidth' ||
					k === 'explorerWidth',
			);
		if (widthOnlyPatch) {
			persistLiteTrailing();
		} else {
			persistLite(next);
		}
		if (patch.bgImage !== undefined) {
			if (next.bgImage) {
				void setKv(BG_KV_KEY, next.bgImage);
			} else {
				void deleteKv(BG_KV_KEY);
			}
		}
		set(next);
	},
	selectProfile(id) {
		const cur = get();
		const profile = cur.profiles.find(p => p.id === id);
		if (!profile) {
			return;
		}
		const next = applyActiveProfile(cur, profile);
		persistLite(next);
		set(next);
	},
	addProfile(partial) {
		const cur = get();
		const id = newProfileId();
		const model = partial?.model ?? cur.model;
		const profile: ModelProfile = {
			id,
			provider: partial?.provider ?? 'deepseek',
			model,
			apiKey: partial?.apiKey ?? '',
			baseUrl: partial?.baseUrl ?? '',
			name: partial?.name ?? '',
			note: partial?.note ?? '',
			website: partial?.website ?? '',
			contextLimit: partial?.contextLimit,
			maxOutputTokens: partial?.maxOutputTokens,
			models: normalizeModels(partial?.models, {
				model,
				contextLimit: partial?.contextLimit,
				maxOutputTokens: partial?.maxOutputTokens,
			}),
		};
		const next = applyActiveProfile(
			{...cur, profiles: [...cur.profiles, profile]},
			profile,
		);
		persistLite(next);
		set(next);
		return id;
	},
	updateProfile(id, partial) {
		const cur = get();
		const existing = cur.profiles.find(p => p.id === id);
		if (!existing) {
			return;
		}
		const contextLimit =
			partial?.contextLimit ?? existing.contextLimit;
		const maxOutputTokens =
			partial?.maxOutputTokens ?? existing.maxOutputTokens;
		const models = normalizeModels(partial?.models ?? existing.models, {
			model: partial?.model ?? existing.model,
			contextLimit,
			maxOutputTokens,
		});
		// 当模型集合被替换时，保证激活模型仍指向集合中的某一个。
		const wantedModel = partial?.model ?? existing.model;
		const model = models.some(m => m.id === wantedModel)
			? wantedModel
			: (models[0]?.id ?? wantedModel);
		const profile: ModelProfile = {
			...existing,
			...partial,
			provider: partial?.provider ?? existing.provider,
			model,
			apiKey: partial?.apiKey ?? existing.apiKey,
			baseUrl: partial?.baseUrl ?? existing.baseUrl,
			name: partial?.name ?? existing.name,
			note: partial?.note ?? existing.note,
			website: partial?.website ?? existing.website,
			contextLimit,
			maxOutputTokens,
			models,
		};
		const profiles = cur.profiles.map(p => (p.id === id ? profile : p));
		// 仅编辑当前激活账号时同步顶层 provider/model/apiKey/baseUrl；
		// 编辑其它账号只就地保存，不切换激活账号。
		const next =
			cur.activeProfileId === id
				? applyActiveProfile({...cur, profiles}, profile)
				: {...cur, profiles};
		persistLite(next);
		set(next);
	},
	removeProfile(id) {
		const cur = get();
		if (cur.profiles.length <= 1) {
			return;
		}
		const profiles = cur.profiles.filter(p => p.id !== id);
		if (profiles.length === cur.profiles.length) {
			return;
		}
		const nextId =
			cur.activeProfileId === id ? profiles[0].id : cur.activeProfileId;
		const selected = profiles.find(p => p.id === nextId) ?? profiles[0];
		const next = applyActiveProfile({...cur, profiles}, selected);
		persistLite(next);
		set(next);
	},
	openSettings(tab) {
		set({
			settingsModalOpen: true,
			settingsInitialTab: tab ?? 'appearance',
		});
	},
	closeSettings() {
		set({settingsModalOpen: false});
	},
	resolvedBaseUrl() {
		const {baseUrl, provider} = get();
		let url = (baseUrl.trim() || PROVIDER_DEFAULT_URL[provider]).replace(
			/\/+$/,
			'',
		);
		if (provider === 'deepseek' && url === 'https://api.deepseek.com') {
			url = PROVIDER_DEFAULT_URL.deepseek;
		}
		return url;
	},
}));
