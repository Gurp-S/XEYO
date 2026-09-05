import {
	PROMPT_CHIP_MAX_PX,
	PROMPT_CHIP_RADIUS_PX,
	PROMPT_VIEW_CAP_VAR,
	STICKY_SELF_WALLPAPER,
	syncPromptViewCapVar,
} from './stickyTypes';

/**
 * documentElement 级 `data-xy-selfwallpaper` 标记的引用计数。
 *
 * 主聊天 MessageList 常驻 + ImmersiveLayer 内嵌第二份 MessageList 时会并存两个实例：
 * 若各自在卸载时无脑 `delete` 全局 attr，退出沉浸层会让仍存活的主列表失去壁纸复刻
 * 背景规则（冒烟 #6：吸顶/编辑气泡变透明）。故改为 acquire/release 配对，
 * 只有最后一个持有者释放时才删除 attr。
 */
let selfWallpaperHolders = 0;

export function acquireSelfWallpaper(): void {
	if (!STICKY_SELF_WALLPAPER) {
		return;
	}
	selfWallpaperHolders += 1;
	if (typeof document !== 'undefined') {
		document.documentElement.dataset.xySelfwallpaper = '1';
	}
}

export function releaseSelfWallpaper(): void {
	if (!STICKY_SELF_WALLPAPER) {
		return;
	}
	selfWallpaperHolders = Math.max(0, selfWallpaperHolders - 1);
	if (selfWallpaperHolders === 0 && typeof document !== 'undefined') {
		delete document.documentElement.dataset.xySelfwallpaper;
	}
}

export function px(value: number): number {
	return Math.round(value);
}

/** 解析 AppShell 暴露的 "--xy-bg-draw-pos"（"12px 34px"）为 px 坐标。 */
export function parsePxPair(raw: string): {x: number; y: number} {
	const parts = raw.trim().split(/\s+/);
	const x = Number.parseFloat(parts[0] ?? '');
	const y = Number.parseFloat(parts[1] ?? parts[0] ?? '');
	return {x: Number.isFinite(x) ? x : 0, y: Number.isFinite(y) ? y : 0};
}

/**
 * 读 L0 壁纸实际绘制原点（AppShell 暴露的 --xy-bg-draw-pos）。
 *
 * Bug 2：该 var 只定义在 AppShell 内层容器 div 上（不会向上继承到 documentElement），
 * 之前从 `document.documentElement` 读取恒返回 ''→{0,0}，导致 pin 背景错位。必须从
 * var 定义点的*后代*（overlay / 气泡等）读取 —— CSS 自定义属性只向下继承。
 */
export function readBgDrawPos(scopeEl: HTMLElement | null): {x: number; y: number} {
	if (!scopeEl) {
		return {x: 0, y: 0};
	}
	return parsePxPair(
		getComputedStyle(scopeEl).getPropertyValue('--xy-bg-draw-pos'),
	);
}

/** SVG 圆角矩形（顺时针），供 clip-path path(evenodd) 打孔 */
export function roundedRectPath(
	x: number,
	y: number,
	w: number,
	h: number,
	radius: number,
): string {
	const r = Math.max(0, Math.min(radius, w / 2, h / 2));
	if (r <= 0) {
		return `M${x} ${y}h${w}v${h}h${-w}z`;
	}
	return [
		`M${x + r} ${y}`,
		`H${x + w - r}`,
		`A${r} ${r} 0 0 1 ${x + w} ${y + r}`,
		`V${y + h - r}`,
		`A${r} ${r} 0 0 1 ${x + w - r} ${y + h}`,
		`H${x + r}`,
		`A${r} ${r} 0 0 1 ${x} ${y + h - r}`,
		`V${y + r}`,
		`A${r} ${r} 0 0 1 ${x + r} ${y}`,
		'Z',
	].join('');
}

export function clipPathPolygonHoles(
	sw: number,
	sh: number,
	holes: {x: number; y: number; w: number; h: number; r?: number}[],
): string {
	if (holes.length === 0 || sw <= 0 || sh <= 0) {
		return 'none';
	}
	let d = `M0 0H${sw}V${sh}H0Z`;
	for (const hole of holes) {
		d += roundedRectPath(
			hole.x,
			hole.y,
			hole.w,
			hole.h,
			hole.r ?? PROMPT_CHIP_RADIUS_PX,
		);
	}
	return `path(evenodd, "${d}")`;
}

export function applyClipPath(el: HTMLElement, clip: string) {
	el.style.clipPath = clip;
	el.style.setProperty('-webkit-clip-path', clip);
}

export function applyChipMaxHeight(
	chip: HTMLElement | null,
	enabled: boolean,
): void {
	if (!chip) {
		return;
	}
	if (enabled) {
		/* 同源到统一查看上限：内联引用 PROMPT_VIEW_CAP_VAR，与 .xy-editing-bubble 的
		   CSS 上限同源（都读 documentElement 上由 promptChipMaxPx 投影出来的 var）。
		   先 ensure var 存在，避免首个 flush 时 var 未写成无效 max-height。 */
		syncPromptViewCapVar();
		chip.style.maxHeight = `var(${PROMPT_VIEW_CAP_VAR})`;
		chip.style.overflow = 'hidden';
		return;
	}
	chip.style.maxHeight = '';
	chip.style.overflow = chip.classList.contains('xy-editing-bubble')
		? 'visible'
		: '';
}

/**
 * 打「内容超高」标记（data-xy-overflow='1'）：CSS 据此显示底部渐变淡出遮罩。
 * 用于查看态 pin 克隆 chip 与编辑气泡。幂等。
 */
export function setOverflowFlag(
	el: HTMLElement | null,
	overflow: boolean,
): void {
	if (!el) {
		return;
	}
	const flag = overflow ? '1' : '0';
	if (el.dataset.xyOverflow !== flag) {
		el.dataset.xyOverflow = flag;
	}
}

/** 查看态 pin 克隆 chip / 流内 chip 是否内容超高（被 max-height 截断处的剩余内容）。
    编辑态（含 textarea）按 textarea.scrollHeight vs chip 可见高判断。 */
/** chip 是否内容超高（被 max-height 截断处的剩余内容）→ 底部渐变淡出。
    编辑态（预览 / textarea）按可滚容器的 scrollHeight vs 可见高判断：
    - textarea：其 scrollHeight 溢出气泡可见高；
    - 预览（.xy-edit-preview）：预览容器 scrollHeight 溢出；
    - 查看态 chip / pin 克隆：chip.scrollHeight 溢出 chip.clientHeight。 */
export function isChipOverflowing(chip: HTMLElement | null): boolean {
	if (!chip) {
		return false;
	}
	const ta = chip.querySelector<HTMLElement>('textarea');
	if (ta) {
		return ta.scrollHeight > chip.clientHeight + 1;
	}
	const preview = chip.querySelector<HTMLElement>('.xy-edit-preview');
	if (preview) {
		return (
			preview.scrollHeight > preview.clientHeight + 1 ||
			preview.scrollHeight > chip.clientHeight + 1
		);
	}
	return chip.scrollHeight > chip.clientHeight + 1;
}

/**
 * 吸顶编辑流内占位高度。
 * 进编辑初值 ≤ PROMPT_CHIP_MAX_PX（缺省回退）；展开后跟可视编辑气泡长高，
 * 整体受统一查看上限 promptChipMaxPx 约束（CSS 侧同源 .xy-editing-bubble）。
 */
export function lockPromptChipPlaceholder(
	chip: HTMLElement | null,
	heightPx: number = PROMPT_CHIP_MAX_PX,
): void {
	if (!chip) {
		return;
	}
	const h = Math.max(1, Math.round(heightPx));
	chip.style.height = `${h}px`;
	chip.style.maxHeight = `${h}px`;
	chip.style.overflow = 'hidden';
	chip.style.flexShrink = '0';
}

export function setStickyStuckAttr(node: HTMLElement, stuck: boolean): boolean {
	const wasStuck = node.getAttribute('data-xy-stuck') === '1';
	if (wasStuck === stuck) {
		if (stuck && !node.classList.contains('xy-prompt-is-stuck')) {
			node.classList.add('xy-prompt-is-stuck');
		}
		return false;
	}
	if (stuck) {
		node.setAttribute('data-xy-stuck', '1');
		node.classList.add('xy-prompt-is-stuck');
	} else {
		node.removeAttribute('data-xy-stuck');
		node.classList.remove('xy-prompt-is-stuck');
	}
	return true;
}

/**
 * 查看态 chip（clamp 的宿主 .xy-user-prompt）内容超高 → 打 data-xy-overflow。
 *
 * PromptTextClamp 的 RO/MO 常驻每个流内 chip：内容/宽度一变即重估，覆盖
 * 「从未经历吸顶/编辑的冷载超长历史气泡」——此前该标记只在 sticky flush 路径
 * 写入（apply/clearAll），collect() 无 stuck/editing/pin 时提前 return，导致
 * 长历史气泡被 CSS max-height 硬切却无底部渐隐。此处统一走 isChipOverflowing
 * （编辑气泡/预览分支同源），与 pinOverlay/controller 的口径一致。
 */
export function syncPromptClampOverflow(clamp: HTMLElement | null): void {
	if (!clamp) {
		return;
	}
	const chip =
		clamp.closest<HTMLElement>('.xy-user-prompt, [data-xy-prompt-chip]') ??
		null;
	if (!chip) {
		return;
	}
	setOverflowFlag(chip, isChipOverflowing(chip));
}
