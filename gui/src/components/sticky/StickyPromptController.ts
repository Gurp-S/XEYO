import type {ChatMessage} from '@/lib/types';
import {clearPinOverlay, pinMessageEditable, syncPinOverlay} from './pinOverlay';
import {
	checkBeginEditContract,
	checkEditingSnapContract,
	checkEndEditContract,
	reportStickyContract,
	type StickyContractViolation,
} from './stickyContract';
import {
	applyChipMaxHeight,
	applyClipPath,
	clipPathPolygonHoles,
	isChipOverflowing,
	lockPromptChipPlaceholder,
	px,
	readBgDrawPos,
	setOverflowFlag,
	setStickyStuckAttr,
	syncPromptClampOverflow,
} from './stickyGeometry';
import {
	PROMPT_CHIP_MAX_PX,
	PROMPT_CHIP_RADIUS_PX,
	STICKY_CLIP_SIZE_STEP_PX,
	STICKY_EXIT_SLOP_PX,
	STICKY_HOLE_PAD_PX,
	STICKY_SELF_WALLPAPER,
	STICKY_TOP_PX,
	promptChipMaxPx,
	type PinView,
	type StickyBeginEditResult,
	type StickyDomBind,
	type StickyFlushResult,
	type StickyPhase,
	type StuckSnap,
} from './stickyTypes';

export type StickyPromptControllerOptions = {
	getMessages: () => ChatMessage[];
	/** React 侧同步 edit portal host（可为 null） */
	onEditPortalHostChange?: (host: HTMLElement | null) => void;
	onLayoutMute?: () => void;
};

/**
 * Sticky 用户气泡唯一真相源。
 *
 * 状态机：`idle` → `stuck`（overlay 文本 pin）→ `editing`（portal）→ `idle`
 *
 * 契约见 `stickyContract.ts`（STICKY_CONTRACT_VERSION）；开发态 beginEdit/collect/endEdit 会校验。
 *
 * MessageList 只应调用本类 API，勿再直接改 pin DOM / clip / max-height。
 */
export class StickyPromptController {
	private phase: StickyPhase = {kind: 'idle'};
	private scroller: HTMLElement | null = null;
	private content: HTMLElement | null = null;
	private overlay: HTMLElement | null = null;

	private readonly stickyEls = new Map<string, HTMLElement>();
	private readonly stickyEditable = new Map<string, boolean>();
	private readonly pinDomNodes = new Map<string, HTMLElement>();
	private readonly lastPinLayout = new Map<string, PinView>();
	private readonly stuckStateCache = new Map<HTMLElement, boolean>();

	private pins: PinView[] = [];
	private clipDirty = false;
	private lastClipSize = {w: 1, h: 1};
	private lastContentClip: string | null = null;

	private editingId: string | null = null;
	private editPortalHost: HTMLElement | null = null;
	private editPlaceholderHeight = PROMPT_CHIP_MAX_PX;
	private streaming = false;

	private layoutMute = false;
	private layoutMuteTimer: ReturnType<typeof setTimeout> | null = null;

	/** 总开关（设置→气泡吸顶，默认关）。关闭时零吸附：不收集几何、不建 pin/hole/portal。 */
	private enabled = true;

	private readonly getMessages: () => ChatMessage[];
	private readonly onEditPortalHostChange?: (host: HTMLElement | null) => void;
	private readonly onLayoutMute?: () => void;

	constructor(opts: StickyPromptControllerOptions) {
		this.getMessages = opts.getMessages;
		this.onEditPortalHostChange = opts.onEditPortalHostChange;
		this.onLayoutMute = opts.onLayoutMute;
	}

	isEnabled(): boolean {
		return this.enabled;
	}

	/** 运行时开关：关闭立即清残留（pin/hole/portal/吸顶隐藏），回到纯流内气泡。 */
	setEnabled(on: boolean): void {
		if (this.enabled === on) {
			return;
		}
		this.enabled = on;
		if (!on) {
			this.editingId = null;
			this.editPortalHost = null;
			this.clearAll();
			this.phase = {kind: 'idle'};
		}
	}

	getPhase(): StickyPhase {
		return this.phase;
	}

	getEditPortalHost(): HTMLElement | null {
		return this.editPortalHost;
	}

	getEditPlaceholderHeight(): number {
		return this.editPlaceholderHeight;
	}

	/**
	 * 编辑态流内占位跟可视气泡同步。返回是否变更。
	 * 可视编辑气泡受统一查看上限（CSS .xy-editing-bubble）约束，测量值 ≤ 该上限。
	 */
	setEditPlaceholderHeight(heightPx: number): boolean {
		if (!this.enabled) {
			/* 就地编辑无 portal 占位概念：不锁 chip，返回「无变更」。 */
			return false;
		}
		const h = Math.max(1, Math.round(heightPx));
		if (h === this.editPlaceholderHeight) {
			return false;
		}
		this.editPlaceholderHeight = h;
		if (this.editingId) {
			const shell = this.stickyEls.get(this.editingId);
			const chip =
				shell?.querySelector<HTMLElement>('[data-xy-prompt-chip]') ?? null;
			lockPromptChipPlaceholder(chip, h);
		}
		return true;
	}

	/** overlay 上可视编辑气泡高度；无 portal / 未挂载时返回 null */
	measureVisibleEditHeight(): number | null {
		const host = this.editPortalHost;
		if (!host) {
			return null;
		}
		const visible =
			host.querySelector<HTMLElement>(
				'.xy-editing-bubble, [data-xy-prompt-chip]',
			) ??
			(host.firstElementChild instanceof HTMLElement
				? host.firstElementChild
				: null);
		if (!visible) {
			return null;
		}
		return Math.max(1, px(visible.getBoundingClientRect().height));
	}

	getPinDomNodes(): Map<string, HTMLElement> {
		return this.pinDomNodes;
	}

	getStickyEditable(): Map<string, boolean> {
		return this.stickyEditable;
	}

	isLayoutMuted(): boolean {
		return this.layoutMute;
	}

	hasShells(): boolean {
		return this.stickyEls.size > 0;
	}

	forEachShell(cb: (id: string, node: HTMLElement) => void): void {
		for (const [id, node] of this.stickyEls) {
			cb(id, node);
		}
	}

	bindDom(bind: StickyDomBind): void {
		this.scroller = bind.scroller;
		this.content = bind.content;
		this.overlay = bind.overlay;
	}

	setStreaming(on: boolean): void {
		this.streaming = on;
	}

	setEditingId(id: string | null): void {
		this.editingId = id;
		if (!id && this.phase.kind === 'editing') {
			this.reconcilePhaseFromPins();
		}
	}

	muteLayoutSnap(ms = 80): void {
		this.layoutMute = true;
		this.onLayoutMute?.();
		if (this.layoutMuteTimer !== null) {
			clearTimeout(this.layoutMuteTimer);
		}
		this.layoutMuteTimer = setTimeout(() => {
			this.layoutMuteTimer = null;
			this.layoutMute = false;
		}, ms);
	}

	/** 开发态契约报告；测试可用 verifyContract({throwOnViolation:true}) */
	private reportContract(violations: StickyContractViolation[]): void {
		if (
			typeof import.meta === 'undefined' ||
			!import.meta.env?.DEV ||
			violations.length === 0
		) {
			return;
		}
		reportStickyContract(violations);
	}

	/**
	 * 主动跑一遍契约检查（编辑中）。返回违规列表。
	 * 供测试 / 诊断；生产可忽略。
	 */
	verifyContract(opts?: {throwOnViolation?: boolean}): StickyContractViolation[] {
		if (!this.editingId) {
			return [];
		}
		const snap = this.collect();
		if (!snap) {
			return [];
		}
		const host = this.editPortalHost;
		const visible =
			host?.querySelector<HTMLElement>('.xy-editing-bubble') ??
			(host?.firstElementChild instanceof HTMLElement
				? host.firstElementChild
				: null);
		const vRect = visible?.getBoundingClientRect();
		const violations = checkEditingSnapContract(
			{
				editingId: this.editingId,
				snap,
				visibleEditHeight: vRect ? px(vRect.height) : null,
				visibleEditWidth: vRect ? px(vRect.width) : null,
			},
			{legacyHoles: !STICKY_SELF_WALLPAPER},
		);
		if (opts?.throwOnViolation) {
			reportStickyContract(violations, {throwOnViolation: true});
		}
		return violations;
	}

	registerShell(id: string, node: HTMLElement, editable: boolean): boolean {
		const same =
			this.stickyEls.get(id) === node &&
			this.stickyEditable.get(id) === editable;
		if (same) {
			return false;
		}
		this.stickyEls.set(id, node);
		this.stickyEditable.set(id, editable);
		return true;
	}

	unregisterShell(id: string): boolean {
		if (!this.stickyEls.has(id)) {
			return false;
		}
		this.stickyEls.delete(id);
		this.stickyEditable.delete(id);
		return true;
	}

	/**
	 * 吸顶编辑入口：idle/stuck → editing。
	 * 契约：
	 * - 流内占位初值 = 进编辑前芯片实高（≤88），禁止一律撑到 88
	 * - 展开后占位/洞跟可视编辑气泡长高（MessageList RO → setEditPlaceholderHeight）
	 * - 可见编辑 UI 只在 portal 上长高；洞跟可视气泡整框（含 pad），pin 顶边跟活 chip
	 * - 编辑期间强制 stuck，禁止 portal 掉回流内
	 */
	beginEdit(message: {
		id: string;
		text: string;
	}): StickyBeginEditResult {
		if (!this.enabled) {
			/* 关闭时编辑在原地展开：不建 portal、不锁流内占位、不吸附。
			   scrollTop 保留原值供调用方按需跟随（hook 就地路径会自己保持可见）。 */
			const scroller = this.scroller;
			this.editingId = message.id;
			this.phase = {kind: 'editing', id: message.id};
			this.editPlaceholderHeight = PROMPT_CHIP_MAX_PX;
			return {
				portalHost: null,
				scrollTop: scroller?.scrollTop ?? null,
				usedPortal: false,
				placeholderHeight: PROMPT_CHIP_MAX_PX,
			};
		}
		const scroller = this.scroller;
		const scrollTop = scroller?.scrollTop ?? null;
		this.editingId = message.id;

		const shell = this.stickyEls.get(message.id);
		const stuck = Boolean(
			shell &&
				(shell.getAttribute('data-xy-stuck') === '1' ||
					shell.classList.contains('xy-prompt-is-stuck') ||
					shell.querySelector('.xy-prompt-sticky[data-xy-stuck="1"]')),
		);
		let existingPin = this.pinDomNodes.get(message.id);
		const chip =
			shell?.querySelector<HTMLElement>('[data-xy-prompt-chip]') ?? null;
		const cached = this.lastPinLayout.get(message.id);
		const measured = chip ? px(chip.getBoundingClientRect().height) : 0;
		const placeholderHeight = Math.max(
			1,
			cached && cached.height > 0
				? cached.height
				: measured > 0
					? measured
					: PROMPT_CHIP_MAX_PX,
		);
		this.editPlaceholderHeight = placeholderHeight;

		/* A 路线：统一走 portal。已吸顶但 pin 丢失时补宿主；
		   未吸顶（上滚后点编辑）也按 chip 当前视口位置补建宿主，让编辑气泡始终只
		   在 portal 上长高，洞/占位跟着可视编辑气泡走（修复"编辑非吸顶消息长高
		   压住其后继内容"）。未建成宿主（无 shell/chip/overlay）才回退流内编辑。 */
		if (!existingPin && this.overlay && shell && (stuck || chip)) {
			const chipRect = chip?.getBoundingClientRect();
			const sRect = scroller?.getBoundingClientRect();
			const host = document.createElement('div');
			host.dataset.pinId = message.id;
			host.className = 'pointer-events-auto absolute';
			if (chipRect && sRect) {
				host.style.left = `${px(chipRect.left - sRect.left)}px`;
				host.style.top = `${px(chipRect.top - sRect.top)}px`;
				host.style.width = `${px(chipRect.width)}px`;
			}
			this.overlay.appendChild(host);
			this.pinDomNodes.set(message.id, host);
			existingPin = host;
			if (chipRect && chipRect.width > 0) {
				this.lastPinLayout.set(message.id, {
					id: message.id,
					text: message.text,
					left: sRect ? px(chipRect.left - sRect.left) : 0,
					top: sRect ? px(chipRect.top - sRect.top) : 0,
					width: px(chipRect.width),
					height: placeholderHeight,
				});
			}
		}

		/* 只要宿主存在就统一走 portal（不再要求 stuck），非吸顶编辑同样经 portal */
		const usingPortal = Boolean(existingPin);
		const sourceHeight =
			cached && cached.height > 0
				? cached.height
				: measured > 0
					? measured
					: PROMPT_CHIP_MAX_PX;

		if (!usingPortal || !existingPin) {
			this.phase = {kind: 'editing', id: message.id};
			if (stuck) {
				lockPromptChipPlaceholder(chip, placeholderHeight);
			} else {
				applyChipMaxHeight(chip, false);
				if (chip) {
					chip.style.overflow = '';
				}
			}
			const result: StickyBeginEditResult = {
				portalHost: null,
				scrollTop,
				usedPortal: false,
				placeholderHeight,
			};
			this.reportContract(
				checkBeginEditContract({
					stuck,
					usedPortal: result.usedPortal,
					portalHost: result.portalHost,
					placeholderHeight: result.placeholderHeight,
					measuredChipHeight: sourceHeight,
				}),
			);
			return result;
		}

		const pinW = Number.parseFloat(existingPin.style.width);
		const pinLeft = Number.parseFloat(existingPin.style.left);
		const pinTop = Number.parseFloat(existingPin.style.top);
		const layoutCached = this.lastPinLayout.get(message.id);
		this.lastPinLayout.set(message.id, {
			id: message.id,
			text: message.text,
			left: Number.isFinite(pinLeft)
				? pinLeft
				: (layoutCached?.left ?? 0),
			top: Number.isFinite(pinTop) ? pinTop : (layoutCached?.top ?? 0),
			width:
				Number.isFinite(pinW) && pinW > 0
					? pinW
					: (layoutCached?.width ?? 1),
			height: placeholderHeight,
		});

		existingPin.replaceChildren();
		existingPin.removeAttribute('role');
		existingPin.removeAttribute('tabindex');
		existingPin.removeAttribute('aria-label');
		existingPin.classList.remove('cursor-text');
		existingPin.style.height = '';
		existingPin.style.maxHeight = '';
		existingPin.style.overflow = 'visible';

		lockPromptChipPlaceholder(chip, placeholderHeight);

		this.setPortalHost(existingPin);
		this.phase = {kind: 'editing', id: message.id};
		this.muteLayoutSnap(120);

		const result: StickyBeginEditResult = {
			portalHost: existingPin,
			scrollTop,
			usedPortal: true,
			placeholderHeight,
		};
		this.reportContract(
			checkBeginEditContract({
				stuck,
				usedPortal: result.usedPortal,
				portalHost: result.portalHost,
				placeholderHeight: result.placeholderHeight,
				measuredChipHeight: sourceHeight,
			}),
		);
		return result;
	}

	/** editing → stuck|idle */
	endEdit(): void {
		this.muteLayoutSnap(120);
		const previousHost = this.editPortalHost;
		this.editingId = null;
		this.editPlaceholderHeight = PROMPT_CHIP_MAX_PX;
		if (this.editPortalHost) {
			const stale = this.editPortalHost;
			const staleId = stale.dataset.pinId;
			this.setPortalHost(null);
			if (staleId) {
				this.pinDomNodes.delete(staleId);
			}
			stale.remove();
		}
		this.reconcilePhaseFromPins();
		this.reportContract(
			checkEndEditContract({
				editingId: this.editingId,
				portalHost: this.editPortalHost,
				previousHost,
			}),
		);
	}

	collect(): StuckSnap | null {
		if (!this.enabled) {
			return null;
		}
		const scroller = this.scroller;
		const content = this.content;
		if (!scroller || !content) {
			return null;
		}
		if (this.stickyEls.size === 0) {
			if (!this.clipDirty && this.pins.length === 0) {
				return null;
			}
			return {
				pins: [],
				holes: [],
				editPortal: null,
				contentW: 1,
				contentH: 1,
				nodes: [],
			};
		}

		const sRect = scroller.getBoundingClientRect();
		const edge = sRect.top;
		const nodes: StuckSnap['nodes'] = [];
		let anyStuck = false;

		for (const [id, shell] of this.stickyEls) {
			const stickyInner =
				shell.querySelector<HTMLElement>('.xy-prompt-sticky') ?? shell;
			const rect = stickyInner.getBoundingClientRect();
			const wasStuck =
				this.stuckStateCache.get(shell) === true ||
				stickyInner.getAttribute('data-xy-stuck') === '1' ||
				shell.getAttribute('data-xy-stuck') === '1';
			/* 提前 enter:chip 顶端距容器顶 ≤ chip 自身高度(已 CSS 封顶后)即交
			   接管,避免"chip 完全被滚出视口才进入吸顶"的延迟感 —— 用户看到的是
			   chip 还差 chip height 左右到顶时,顶部提前出现 pin 替身;原生 sticky
			   是 chip 顶端刚好到顶时才吸顶,视觉上感觉"覆盖了才顶"。exit 用
			   chip height + SLOP 做 hysteresis:chip 完全越出 + 一段惰性才解吸,
			   避免小幅抖动反复进出。rect.height 已含 padding+margin(via getBCR)。 */
			const rectH = Math.max(1, Math.round(rect.height));
			const enter =
				rect.top <= edge + rectH + 0.5 && rect.bottom > edge + 1;
			const exit =
				rect.top > edge + rectH + STICKY_EXIT_SLOP_PX ||
				rect.bottom <= edge + 1;
			/* smoke-test #10 修复：编辑中只对「portal 编辑」（进编辑时已吸顶/已建
			   portal 宿主）强制保持 stuck，防止编辑气泡掉回流内成幽灵框；对
			   「就地编辑」（进编辑时未吸顶）按正常进出判定，不再把流内消息
			   拽到吸顶 portal —— 用户看到的就是"气泡被吸到顶部不复位"。
			   （就地编辑若滚动到吸顶区,自然转 portal 编辑,后续保持 stuck。） */
			const stuck =
				id === this.editingId
					? this.editPortalHost
						? true
						: wasStuck
							? !exit
							: enter
					: wasStuck
						? !exit
						: enter;
			const chip = shell.querySelector<HTMLElement>('[data-xy-prompt-chip]');
			nodes.push({id, node: shell, stuck, chip: chip ?? null});
			if (stuck) {
				anyStuck = true;
			}
		}

		if (
			!anyStuck &&
			!this.clipDirty &&
			this.pins.length === 0 &&
			!this.editingId
		) {
			return null;
		}

		const cRect = content.getBoundingClientRect();
		const nextPins: PinView[] = [];
		const holes: StuckSnap['holes'] = [];
		let editPortal: PinView | null = null;
		// P2-⑩：同屏多个 stuck/编辑气泡的叠层偏移。此前每个气泡按自身 chip 视口矩形
		// 独立定 top，超高时还被强制锚 STICKY_TOP_PX（0），导致「过长限高 sticky 的
		// 吸顶 + 下方编辑态 sticky 吸顶」相互重叠。这里按渲染顺序累加 top+height，
		// 让后一个气泡顶在前一个之下，恢复 native sticky 的推挤效果。
		let lastPinBottom = STICKY_TOP_PX;

		for (const {id, stuck, chip} of nodes) {
			if (!stuck || !chip) {
				continue;
			}

			const chipRect = chip.getBoundingClientRect();
			const scrollLeft = content.scrollLeft;
			const scrollTop = content.scrollTop;
			const text = chip.dataset.promptText ?? '';
			const editingThis = id === this.editingId;
			const cached = this.lastPinLayout.get(id);

			let width = px(chipRect.width);
			/* 统一查看上限：pin/洞钳到 promptChipMaxPx（与 .xy-editing-bubble CSS 上限
			   同源）。长消息满高芯片吸顶时盒底被容器顶住、盒子盖满聊天视口 —— 满高洞
			   会把流式回复整体裁掉（内容 clip 走壁纸），满高 pin（pointer-events:auto
			   且在 scroller 之外）会吞掉滚轮。 */
			const fullHeight = Math.max(1, px(chipRect.height));
			let height = Math.min(fullHeight, promptChipMaxPx());
			/* 与仓库口径一致：pin 相对 scroller（chipRect - sRect） */
			let left = px(chipRect.left - sRect.left);
			let top = px(chipRect.top - sRect.top);
			let holeX = px(chipRect.left - cRect.left + scrollLeft);
			let holeY = px(chipRect.top - cRect.top + scrollTop);
			let holeW = width;
			let holeH = height;
			if (fullHeight > height) {
				/* 芯片满高超上限：吸顶盒 top 已越出视口顶，pin/洞改锚视口顶；
				   洞换算回内容系（两点视口 rect 相减即内容局部坐标，content 自身
				   不滚动，scrollTop 恒 0）。 */
				top = STICKY_TOP_PX;
				holeY = px(sRect.top - cRect.top + STICKY_TOP_PX);
			}

			const pinHost = this.pinDomNodes.get(id);
			const pinVisual =
				pinHost?.querySelector<HTMLElement>(
					'.xy-editing-bubble, .xy-user-prompt, [data-xy-prompt-chip]',
				) ??
				(pinHost?.firstElementChild instanceof HTMLElement
					? pinHost.firstElementChild
					: null);

			const visibleEdit =
				editingThis
					? (this.editPortalHost?.querySelector<HTMLElement>(
							'.xy-editing-bubble, [data-xy-prompt-chip]',
						) ??
						(this.editPortalHost?.firstElementChild instanceof
						HTMLElement
							? this.editPortalHost.firstElementChild
							: null))
					: null;

			if (editingThis && cached && cached.width > 0) {
				/* 宽钉进编辑前几何；高/位由可视气泡覆盖 */
				width = cached.width;
				height = Math.max(
					1,
					cached.height > 0
						? cached.height
						: this.editPlaceholderHeight,
				);
				holeW = width;
				holeH = height;
			} else if (editingThis) {
				height = this.editPlaceholderHeight;
				holeH = height;
			}

			/* 洞跟用户看见的那一层（portal 编辑气泡 / pin 克隆），避免流内 hidden chip 与 pin 几何漂移。
			 * pin 的 left/top/width 仍锚在流内 chip，禁止用 pin 自测回写（会漂出视口导致吸顶气泡消失）。 */
			const holeSource = visibleEdit ?? pinVisual;
			if (holeSource) {
				const vRect = holeSource.getBoundingClientRect();
				holeW = Math.max(1, px(vRect.width));
				holeH = Math.max(1, px(vRect.height));
				holeX = px(vRect.left - cRect.left + scrollLeft);
				holeY = px(vRect.top - cRect.top + scrollTop);
			}

			// P2-⑩：叠层偏移。当前气泡 top 若插到上一个已布局气泡之下方边界之上，
			// 就把它下移到 lastPinBottom 之下，避免与上一个吸顶气泡重叠。
			const minTop = lastPinBottom + STICKY_HOLE_PAD_PX;
			if (top < minTop) {
				const delta = minTop - top;
				top = minTop;
				holeY += delta;
			}

			const layout: PinView = {id, text, left, top, width, height};
			if (top + height > lastPinBottom) {
				lastPinBottom = top + height;
			}
			if (!editingThis) {
				this.lastPinLayout.set(id, layout);
			}
			const pad = STICKY_HOLE_PAD_PX;
			if (!STICKY_SELF_WALLPAPER) {
				/* 旧挖孔路径（灰度关）才需要洞；自绘壁纸路径 pin 背景自带壁纸，不挖孔 */
				holes.push({
					x: holeX - pad,
					y: holeY - pad,
					w: holeW + pad * 2,
					h: holeH + pad * 2,
					/* 外扩 pad 后圆角同步 +pad，角与气泡平行曲线对齐 */
					r: PROMPT_CHIP_RADIUS_PX + pad,
				});
			}
			if (editingThis) {
				editPortal = layout;
			} else {
				nextPins.push(layout);
			}
		}

		const rawW = px(Math.max(content.scrollWidth, cRect.width, 1));
		const rawH = px(Math.max(content.scrollHeight, cRect.height, 1));
		let contentW = rawW;
		let contentH = rawH;
		if (STICKY_SELF_WALLPAPER) {
			/* 自绘壁纸路径无 clip，尺寸无需步进缓存 */
			this.lastClipSize = {w: rawW, h: rawH};
		} else if (this.streaming) {
			const prev = this.lastClipSize;
			contentW = Math.max(
				prev.w,
				Math.ceil(rawW / STICKY_CLIP_SIZE_STEP_PX) * STICKY_CLIP_SIZE_STEP_PX,
			);
			contentH = Math.max(
				prev.h,
				Math.ceil(rawH / STICKY_CLIP_SIZE_STEP_PX) * STICKY_CLIP_SIZE_STEP_PX,
			);
			this.lastClipSize = {w: contentW, h: contentH};
		} else {
			this.lastClipSize = {w: rawW, h: rawH};
		}

		const snap: StuckSnap = {
			pins: nextPins,
			holes,
			editPortal,
			contentW,
			contentH,
			nodes,
		};
		this.assertEditingSnap(snap);
		return snap;
	}

	private assertEditingSnap(snap: StuckSnap): void {
		if (!this.editingId) {
			return;
		}
		const host = this.editPortalHost;
		const visible =
			host?.querySelector<HTMLElement>('.xy-editing-bubble') ??
			(host?.firstElementChild instanceof HTMLElement
				? host.firstElementChild
				: null);
		const vRect = visible?.getBoundingClientRect();
		this.reportContract(
			checkEditingSnapContract(
				{
					editingId: this.editingId,
					snap,
					visibleEditHeight: vRect ? px(vRect.height) : null,
					visibleEditWidth: vRect ? px(vRect.width) : null,
				},
				{legacyHoles: !STICKY_SELF_WALLPAPER},
			),
		);
	}

	apply(snap: StuckSnap): StickyFlushResult {
		const content = this.content;
		let layoutMutated = false;

		for (const {id, node, stuck, chip} of snap.nodes) {
			if (setStickyStuckAttr(node, stuck)) {
				layoutMutated = true;
			}
			this.stuckStateCache.set(node, stuck);
			if (!chip) {
				continue;
			}
			const editingThis = this.editingId === id;
			if (editingThis) {
				lockPromptChipPlaceholder(chip, this.editPlaceholderHeight);
				/* 就地编辑（非 portal）：气泡即 chip，按 textarea 溢出打标 → 底部渐变淡出 */
				setOverflowFlag(chip, isChipOverflowing(chip));
				continue;
			}
			/* cae4584：吸顶不钳 max-height，流内 chip 仅 visibility 隐藏 */
			const hadMax = chip.style.maxHeight !== '';
			applyChipMaxHeight(chip, false);
			if (hadMax) {
				layoutMutated = true;
			}
			if (chip.classList.contains('invisible')) {
				chip.classList.remove('invisible');
			}
			/* 流内 chip 也按 96px+css 封顶；内容超高 → 打标显示底部渐变淡出 */
			setOverflowFlag(chip, isChipOverflowing(chip));
			if (stuck) {
				syncPromptClampOverflow(
					chip.querySelector<HTMLElement>('.xy-prompt-clamp'),
				);
			}
		}

		if (layoutMutated) {
			this.muteLayoutSnap();
		}
		if (!content) {
			this.reconcilePhaseFromSnap(snap);
			return {
				layoutMutated,
				editPortalHost: this.editPortalHost,
				cleared: false,
			};
		}

		if (STICKY_SELF_WALLPAPER) {
			if (this.lastContentClip !== null) {
				/* 清掉灰度前可能残留的挖孔 clip */
				applyClipPath(content, 'none');
				this.lastContentClip = null;
			}
		} else {
			const contentClip = clipPathPolygonHoles(
				snap.contentW,
				snap.contentH,
				snap.holes,
			);
			if (this.lastContentClip !== contentClip) {
				applyClipPath(content, contentClip);
				this.lastContentClip = contentClip;
			}
		}

		this.pins = snap.pins;
		const overlay = this.overlay;
		const portalLayout = snap.editPortal;
		const retainPortalId = portalLayout?.id ?? null;

		syncPinOverlay(
			overlay,
			this.pinDomNodes,
			snap.pins,
			retainPortalId,
			this.stickyEditable,
			this.getMessages(),
			(id) =>
				this.stickyEls
					.get(id)
					?.querySelector<HTMLElement>('[data-xy-prompt-chip]') ?? null,
		);

		if (portalLayout && overlay) {
			let host = this.pinDomNodes.get(portalLayout.id);
			if (!host) {
				host = document.createElement('div');
				host.dataset.pinId = portalLayout.id;
				host.className = 'pointer-events-auto absolute';
				this.pinDomNodes.set(portalLayout.id, host);
				overlay.appendChild(host);
			} else if (host.querySelector('.xy-prompt-clamp')) {
				host.replaceChildren();
				host.removeAttribute('role');
				host.removeAttribute('tabindex');
				host.removeAttribute('aria-label');
				host.classList.remove('cursor-text');
			}
			host.style.left = `${portalLayout.left}px`;
			host.style.top = `${portalLayout.top}px`;
			host.style.width = `${portalLayout.width}px`;
			host.style.height = '';
			host.style.maxHeight = '';
			host.style.overflow = 'visible';
			const editBubble =
				host.querySelector<HTMLElement>('.xy-editing-bubble') ??
				(host.firstElementChild instanceof HTMLElement
					? host.firstElementChild
					: null);
			/* 编辑气泡内容超高 → 打 data-xy-overflow 供 CSS 显示底部渐变淡出；
			   textarea 内部滚动看全文。isChipOverflowing 按 textarea.scrollHeight
			   vs 气泡被封顶的 clientHeight 判断，避免量到未 shrink 的瞬时盒。 */
			setOverflowFlag(editBubble, isChipOverflowing(editBubble));
			if (STICKY_SELF_WALLPAPER) {
				/* portal 编辑气泡自绘壁纸：与 pin 相同的“绘制原点 − 气泡窗口原点”对齐 */
				const bubble = editBubble;
				if (bubble) {
					const oRect = overlay.getBoundingClientRect();
					/* Bug 2：draw 从 overlay（AppShell 容器后代）读取，勿用 documentElement */
					const draw = readBgDrawPos(overlay);
					const pos = `0 0, 0 0, ${px(draw.x - (oRect.left + portalLayout.left))}px ${px(draw.y - (oRect.top + portalLayout.top))}px`;
					if (bubble.style.backgroundPosition !== pos) {
						bubble.style.backgroundPosition = pos;
					}
				}
			}
			overlay.setAttribute('aria-hidden', 'false');
			if (this.editPortalHost !== host) {
				this.setPortalHost(host);
			}
		} else if (this.editPortalHost) {
			const stale = this.editPortalHost;
			const staleId = stale.dataset.pinId;
			this.setPortalHost(null);
			if (staleId) {
				this.pinDomNodes.delete(staleId);
			}
			stale.remove();
		}

		this.clipDirty =
			snap.pins.length > 0 ||
			snap.nodes.some(n => n.stuck) ||
			Boolean(portalLayout);

		this.reconcilePhaseFromSnap(snap);
		return {
			layoutMutated,
			editPortalHost: this.editPortalHost,
			cleared: false,
		};
	}

	flush(): StickyFlushResult {
		if (!this.enabled) {
			return {
				layoutMutated: false,
				editPortalHost: null,
				cleared: false,
			};
		}
		const snap = this.collect();
		if (snap) {
			return this.apply(snap);
		}
		if (this.streaming && this.stickyEls.size > 0) {
			return {
				layoutMutated: false,
				editPortalHost: this.editPortalHost,
				cleared: false,
			};
		}
		if (
			this.pinDomNodes.size > 0 ||
			this.pins.length > 0 ||
			this.clipDirty
		) {
			this.clearAll();
			return {
				layoutMutated: true,
				editPortalHost: null,
				cleared: true,
			};
		}
		this.phase = {kind: 'idle'};
		return {
			layoutMutated: false,
			editPortalHost: this.editPortalHost,
			cleared: false,
		};
	}

	clearAll(): void {
		this.muteLayoutSnap();
		const content = this.content;
		for (const shell of this.stickyEls.values()) {
			setStickyStuckAttr(shell, false);
			this.stuckStateCache.set(shell, false);
			const chip = shell.querySelector<HTMLElement>('[data-xy-prompt-chip]');
			chip?.classList.remove('invisible');
			applyChipMaxHeight(chip, false);
			/* 流内 chip 仍按 CSS 96px 封顶；内容超高 → 打标显示底部渐变淡出 */
			setOverflowFlag(chip, isChipOverflowing(chip));
		}
		if (content) {
			applyClipPath(content, 'none');
			this.lastContentClip = null;
		}
		this.pins = [];
		clearPinOverlay(this.overlay, this.pinDomNodes);
		this.setPortalHost(null);
		this.clipDirty = false;
		this.lastClipSize = {w: 1, h: 1};
		this.phase = this.editingId
			? {kind: 'editing', id: this.editingId}
			: {kind: 'idle'};
	}

	isPinEditable(id: string): boolean {
		return pinMessageEditable(id, this.stickyEditable, this.getMessages());
	}

	isShellStuck(id: string): boolean {
		const shell = this.stickyEls.get(id);
		if (!shell) {
			return false;
		}
		return (
			shell.getAttribute('data-xy-stuck') === '1' ||
			shell.classList.contains('xy-prompt-is-stuck') ||
			Boolean(shell.querySelector('[data-xy-stuck="1"]'))
		);
	}

	resetSession(): void {
		this.editingId = null;
		this.lastPinLayout.clear();
		this.stuckStateCache.clear();
		this.clearAll();
		this.phase = {kind: 'idle'};
	}

	dispose(): void {
		if (this.layoutMuteTimer !== null) {
			clearTimeout(this.layoutMuteTimer);
			this.layoutMuteTimer = null;
		}
		clearPinOverlay(this.overlay, this.pinDomNodes);
		this.setPortalHost(null);
		this.stickyEls.clear();
		this.stickyEditable.clear();
		this.phase = {kind: 'idle'};
	}

	private setPortalHost(host: HTMLElement | null): void {
		if (this.editPortalHost === host) {
			return;
		}
		this.editPortalHost = host;
		this.onEditPortalHostChange?.(host);
	}

	private reconcilePhaseFromSnap(snap: StuckSnap): void {
		if (this.editingId && snap.editPortal?.id === this.editingId) {
			this.phase = {kind: 'editing', id: this.editingId};
			return;
		}
		if (this.editingId) {
			this.phase = {kind: 'editing', id: this.editingId};
			return;
		}
		const ids = snap.pins.map(p => p.id);
		this.phase =
			ids.length > 0 ? {kind: 'stuck', ids} : {kind: 'idle'};
	}

	private reconcilePhaseFromPins(): void {
		if (this.editingId) {
			this.phase = {kind: 'editing', id: this.editingId};
			return;
		}
		const ids = this.pins.map(p => p.id);
		this.phase =
			ids.length > 0 ? {kind: 'stuck', ids} : {kind: 'idle'};
	}
}
