import type {ChatMessage} from '@/lib/types';

/** 状态机：idle → stuck(pin) → editing(portal) → idle */
export type StickyPhase =
	| {kind: 'idle'}
	| {kind: 'stuck'; ids: readonly string[]}
	| {kind: 'editing'; id: string};

export type PinView = {
	id: string;
	text: string;
	left: number;
	top: number;
	width: number;
	height: number;
};

export type StuckNodeView = {
	id: string;
	node: HTMLElement;
	stuck: boolean;
	chip: HTMLElement | null;
};

export type StuckSnap = {
	pins: PinView[];
	holes: {x: number; y: number; w: number; h: number; r?: number}[];
	editPortal: PinView | null;
	contentW: number;
	contentH: number;
	nodes: StuckNodeView[];
};

export type StickyFlushResult = {
	layoutMutated: boolean;
	editPortalHost: HTMLElement | null;
	cleared: boolean;
};

export type StickyBeginEditResult = {
	/** 已切到 editing：portal 宿主（可能为 null 表示非吸顶就地编辑） */
	portalHost: HTMLElement | null;
	/** 调用方应钉住的 scrollTop */
	scrollTop: number | null;
	usedPortal: boolean;
	/** 流内占位必须等于进编辑前芯片实高，否则 transcript 会被撑开跳动 */
	placeholderHeight: number;
};

export type StickyDomBind = {
	scroller: HTMLElement | null;
	content: HTMLElement | null;
	overlay: HTMLElement | null;
};

export type StickyMessagesLookup = () => ChatMessage[];

/** 与气泡 rounded-2xl（1rem）一致 */
export const PROMPT_CHIP_RADIUS_PX = 16;
/** 编辑占位缺省初值（历史常量；查看/编辑统一上限见 promptChipMaxPx） */
export const PROMPT_CHIP_MAX_PX = 88;
/**
 * 查看 pin / 编辑气泡统一高度上限：与 Composer 展开高度同源（min(58vh, 440px)）。
 * 单一来源三处引用：collect() 的 pin/洞钳制、applyChipMaxHeight、
 * chat.css .xy-editing-bubble（字面量 min(58vh, 440px)）——改值须 JS/CSS 两处同步。
 */
export const PROMPT_CHIP_VIEW_MAX_VH_PCT = 58;
export const PROMPT_CHIP_VIEW_MAX_PX = 120;
export function promptChipMaxPx(viewportHeight?: number): number {
	const vh =
		typeof viewportHeight === 'number' &&
		Number.isFinite(viewportHeight) &&
		viewportHeight > 0
			? viewportHeight
			: typeof window !== 'undefined' &&
				  Number.isFinite(window.innerHeight) &&
				  window.innerHeight > 0
				? window.innerHeight
				: 0;
	const byVh = Math.round(vh * (PROMPT_CHIP_VIEW_MAX_VH_PCT / 100));
	return Math.min(
		byVh > 0 ? byVh : PROMPT_CHIP_VIEW_MAX_PX,
		PROMPT_CHIP_VIEW_MAX_PX,
	);
}

/**
 * 查看/编辑统一高度上限的 CSS 变量名（单一来源）。
 *
 * 阶段1 收尾（Bug 1）：查看态 pin 用 JS `promptChipMaxPx()`（基于 window.innerHeight），
 * 编辑态 `.xy-editing-bubble` 用 CSS 字面量 `min(58vh, 440px)` —— 两套基准（innerHeight
 * vs vh）在 Tauri WebView 里会漂移，导致最高高度不一致。此处把上限投影为一个 CSS 变量，
 * 供 `.xy-editing-bubble`（CSS `max-height: var(...)`）与 pin 内联 max-height 共同读取，
 * 二者同源到 `promptChipMaxPx()`。
 */
export const PROMPT_VIEW_CAP_VAR = '--xy-prompt-view-cap';

/** 统一上限的 CSS 值（如"96px"），是 promptChipMaxPx 的 CSS 投影。 */
export function promptViewCapCss(): string {
	return `${promptChipMaxPx()}px`;
}

/**
 * 把统一上限写到 documentElement（html）上的 PROMPT_VIEW_CAP_VAR。
 * 幂等：值未变不重写，避免每次 flush 都触发样式重算。
 * 在 AppShell 挂载/窗口 resize 时调用（编辑气泡 CSS 随 var 自动更新）。
 */
export function syncPromptViewCapVar(): string {
	const value = promptViewCapCss();
	if (typeof document !== 'undefined') {
		const el = document.documentElement;
		if (el.style.getPropertyValue(PROMPT_VIEW_CAP_VAR) !== value) {
			el.style.setProperty(PROMPT_VIEW_CAP_VAR, value);
		}
	}
	return value;
}

/**
 * 阶段1 灰度开关：吸顶 pin / portal 编辑气泡自绘壁纸（背景复刻 L0，替代 clip-path 挖孔）。
 * localStorage 'xy.stickySelfWallpaper' = '0' 时回滚旧挖孔路径（STICKY_CONTRACT C5 同步切换）。
 */
export const STICKY_SELF_WALLPAPER =
	typeof localStorage !== 'undefined'
		? localStorage.getItem('xy.stickySelfWallpaper') !== '0'
		: true;
/** 吸顶贴聊天顶边（往上收，避免顶区留空） */
export const STICKY_TOP_PX = 0;
export const STICKY_EXIT_SLOP_PX = 14;
/** 洞略外扩只为抗锯齿；圆角必须 = 气泡半径 + pad，否则角上对不齐 */
export const STICKY_HOLE_PAD_PX = 1;
export const STICKY_CLIP_SIZE_STEP_PX = 128;

export const PIN_CHIP_CLASS =
	'xy-user-prompt xy-surface xy-user-bubble mx-auto max-w-3xl overflow-hidden rounded-2xl px-4 pt-3.5 pb-2.5';
export const PIN_TEXT_CLASS =
	'xy-chat-text min-w-0 whitespace-pre-wrap font-sans text-[15px] leading-relaxed';
