import {useLayoutEffect, useRef, type ReactNode} from 'react';
import {createCaretRemeasure} from './caretRemeasure';

/**
 * 自绘光标 + 镜像覆盖层(2026-09-08 双档运动改版,初版同日)。
 *
 * 结构:textarea 文字 text-transparent,本组件逐字符渲染镜像文本并放一个
 * 自绘光标 div。颜色跟 var(--xy-ink)(浅色主题=墨,深色主题=近白)——
 * 硬编码白色在浅色作曲卡上不可见(2026-09-08 录屏实测),勿改回定值。
 *
 * 运动模型(双档物理,web-motion 逐帧诊断后定稿):
 * - fast 档(连续打字/退格/左右单步):同行且 |dx| ≤ 26px(≈1.5 字) →
 *   68ms 纯 ease-out 紧贴,零过冲不拉伸。Timing 原则:即时反馈 ≤100ms,
 *   旧版每键 150ms 弹簧重启 = 光标永远落后 1-1.5 字符(实测 lag p95 6.4px)。
 * - macro 档(点选/Home/End/换行/粘贴):170ms 轻过冲弹簧(cubic-bezier
 *   y1=1.18,≈3-5% 距离),移动拉伸(19→24px)只在此档,大手势才配得上花活。
 * - snap 档(首次落位/失焦重现/滚动跟踪):位移瞬时。点击聚焦瞬置是原生
 *   行为;滚动跟踪必须 1:1,滞后=脱锚。
 * - 呼吸:停手 560ms 后从最亮起步 dip 到 0.35(旧 0.18 太狠),周期 1.06s;
 *   打字期间摘除 xy-idle=常亮(相位重启无"忽明忽暗")。
 * - blur 清光全部类 → 基础 opacity:0 真隐没。旧版 blur 还 add('xy-idle'),
 *   而 CSS animation 优先级高于基础声明 → 失焦后光标原地呼吸
 *   (实测 blur 后 opacity 峰值 0.908,2026-09-08),勿改回。
 *
 * 滚动镜像:textarea 超高滚动时 inner 层 translateY(-scrollTop) 同步,
 * 测量在同步之后(span rects 已含平移),光标与文本永不脱锚。
 *
 * 测量内核(与 _design_drafts/composer-caret-styles.html 同源,已机器验证):
 * - 逐字符 span:元素边界不产生断行点,镜像换行与 textarea 完全一致
 *   (不要改回"caret 处插 inline-block 标记"——atomic inline 会在英文单词
 *   中间制造断行点,直接导致光标错位,2026-09-08 已踩坑);
 * - 光标锚定跨行判定:caret 前后字符 top 比较,行尾取下一字符行首;
 * - code point 拆分(emoji/扩展汉字不拆散),caret 仍用 UTF-16 下标
 *   (与 selectionStart 同系),经 cpStarts 映射。
 *
 * 显示策略:
 * - 可见性唯一判据 active && focused:placeCaret 内统一把关 —— 滚动/重测入口
 *   不受 React 依赖驱动,失焦后仍会打进来,不设闸就会"失焦还亮着";
 * - active=false(IME 组词 / 超大文本)→ 整层不渲染,退回原生光标;
 * - 失焦隐没,聚焦浮现;滚动由父级调 apiRef.reposition()(snap 档)。
 *
 * 重测失效源(caretRemeasure.ts,2026-10-01):测量结果只在同一帧内有效。
 * 自动高度动画、分栏/窗口 resize、迟到字体都会改文本落点而不改 value ——
 * 三类来源合并成每帧一次 snap 重测。新增"改布局不改 value"的路径时,必须
 * 要么让容器尺寸进入观察,要么显式调 apiRef.reposition(),否则光标停在旧坐标。
 *
 * 与 Composer 的对齐契约(改 textarea 排版类必须同步这里):
 * px-3 pt-3(12px)、text-[14px]、leading-6(24px)。
 */

export interface CaretColorRange {
	/** UTF-16 下标,闭开区间 [start, end) */
	start: number;
	end: number;
}

export interface TypingCaretApi {
	/** 父级在 textarea scroll 后调用:同步镜像滚动 + snap 重测位置 */
	reposition: () => void;
}

interface TypingCaretProps {
	value: string;
	/** 光标 UTF-16 下标(= textarea selectionStart/End) */
	caret: number;
	caretDir: 'forward' | 'backward' | 'none';
	/** slash 着色区间(闭开,UTF-16 下标) */
	colorRanges: CaretColorRange[];
	/** 末尾灰字 ghost hint(不参与光标测量) */
	ghostHint: string;
	focused: boolean;
	/** false = IME 组词 / 超大文本,不接管显示 */
	active: boolean;
	apiRef?: {current: TypingCaretApi | null};
}

const PAD_X = 12;            /* = textarea px-3 */
const PAD_Y = 12;            /* = textarea pt-3 */
const IDLE_DELAY_MS = 560;   /* 停手后转呼吸的延迟 */
const MICRO_MAX_DX = 26;     /* fast 档上限:同行 ≤≈1.5 字(中文 14px/字) */
const CH_IN_MAX_CP = 12;     /* 字符浮现上限:粘贴/大段插入跳过动画 */

/** 单码点的、且正好落在光标处的增删 = 连续输入手势(打字 / 退格 / 单字上屏)。
 *  这类位移即便因重排跨行(行尾插入挤到下一行),也不是"大跳"。 */
function isSingleCaretEdit(
	prevValue: string,
	value: string,
	caret: number,
): boolean {
	if (prevValue === value) {
		return false;
	}
	let p = 0;
	const maxP = Math.min(prevValue.length, value.length);
	while (p < maxP && prevValue[p] === value[p]) p += 1;
	let s = 0;
	const maxS = Math.min(prevValue.length, value.length) - p;
	while (
		s < maxS &&
		prevValue[prevValue.length - 1 - s] === value[value.length - 1 - s]
	) {
		s += 1;
	}
	const ins = value.slice(p, value.length - s);
	const del = prevValue.slice(p, prevValue.length - s);
	if (Array.from(ins).length + Array.from(del).length !== 1) {
		return false;
	}
	/* 光标紧贴增删点:否则是程序化改写(草稿切换 / 清空)后的落位,不算手势 */
	return caret === p + ins.length;
}

export function TypingCaret({
	value,
	caret,
	caretDir,
	colorRanges,
	ghostHint,
	focused,
	active,
	apiRef,
}: TypingCaretProps) {
	const overlayRef = useRef<HTMLDivElement>(null);
	const innerRef = useRef<HTMLDivElement>(null);
	const caretRef = useRef<HTMLDivElement>(null);
	const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
	/** 光标可见性的唯一判据(active && focused):placeCaret 与退场清理共用。 */
	const liveRef = useRef(active && focused);
	liveRef.current = active && focused;
	const lastPosRef = useRef<{x: number; y: number} | null>(null);
	const onShownRef = useRef(false);
	const prevValueRef = useRef('');
	const recentKeyRef = useRef(0); /* 最近 keydown 时刻:拉伸只认键盘手势 */
	/* 性能改造(2026-09-29 卡顿排查):以下三组缓存把每键的 O(n) DOM 查询/
	   布局重排降为 O(1) —— 只减工作量,不改任何几何结论。 */
	/** 上一次落到 inner 层的滚动平移；相同则完全不写 style(写即失效布局)。 */
	const appliedShiftRef = useRef(0);
	/** textarea 只查一次(每键 querySelector 无谓消耗)。 */
	const taElRef = useRef<HTMLTextAreaElement | null>(null);
	/** 上一次写给 inner 的折行宽(= textarea 内容宽)；相同则完全不写 style。 */
	const appliedWidthRef = useRef(0);
	/** textarea 左右内边距之和(只在换元素时重算)。 */
	const padRef = useRef(PAD_X * 2);
	/** value → code point 数组 + UTF-16 起点表;value 未变则复用。 */
	const cpsCacheRef = useRef<{
		value: string;
		cps: string[];
		cpStarts: number[];
	} | null>(null);
	/** 上一次渲染的逐字符元素表（按公共 code point 前缀复用）。 */
	const charNodesRef = useRef<{
		cps: string[];
		ranges: {start: number; end: number}[];
		nodes: ReactNode[];
	} | null>(null);

	const readCps = (text: string) => {
		const cache = cpsCacheRef.current;
		if (cache && cache.value === text) {
			return cache;
		}
		const cps = Array.from(text);
		const cpStarts: number[] = [];
		let u16 = 0;
		for (const ch of cps) {
			cpStarts.push(u16);
			u16 += ch.length;
		}
		const next = {value: text, cps, cpStarts};
		cpsCacheRef.current = next;
		return next;
	};

	/* 逐字符 span 视图：装饰节点(空文本探针 / 尾哨兵 / ghost)都不是码点，码点 span
	   夹在它们中间且按序对应 code point 下标。取一次视图 → O(1) 按下标直取，取代
	   每键一次 querySelectorAll 全表物化 / 每个插入字符一次 querySelector 全子树扫描。
	   头尾各按 data-ci 逐节点数(头侧 ≤1，尾侧 ≤2：哨兵 + ghost)，不靠位置猜数量。 */
	const readSpanView = () => {
		const kids = innerRef.current?.children ?? null;
		const kidCount = kids ? kids.length : 0;
		const isCi = (i: number) => !!kids![i]?.hasAttribute('data-ci');
		let head = 0;
		while (head < kidCount && !isCi(head)) {
			head += 1;
		}
		let tail = 0;
		while (tail < kidCount - head && !isCi(kidCount - 1 - tail)) {
			tail += 1;
		}
		const count = Math.max(0, kidCount - head - tail);
		return {
			count,
			at(i: number): HTMLSpanElement | null {
				if (i < 0 || i >= count || !kids) {
					return null;
				}
				const el = kids.item(i + head);
				return el instanceof HTMLSpanElement && el.hasAttribute('data-ci')
					? el
					: null;
			},
		};
	};

	/** 清光全部类 → 基础 opacity:0 真隐没。退场与"不该显示"共用同一处,
	 *  防止两条路径各自维护类名表而漂移(CSS animation 优先级高于基础声明,
	 *  漏掉 xy-idle 就会失焦后原地呼吸)。 */
	const hideCaret = (g: HTMLDivElement | null) => {
		if (!g) {
			return;
		}
		g.classList.remove('xy-on', 'xy-moving', 'xy-idle', 'xy-fast', 'xy-snap');
	};

	/** 回亮不加跳变:呼吸中的光标被摘掉 xy-idle 的一瞬间会从当前暗值(最低
	 *  0.35)直接跳到 1,读感就是"闪一下"。这里先把当前实际亮度冻结成起点,
	 *  再用 120ms 斜坡补到常亮;没有动画在跑(常亮态)时什么都不做。 */
	const wakeToFull = (g: HTMLDivElement) => {
		const animating =
			typeof g.getAnimations === 'function' && g.getAnimations().length > 0;
		const dip =
			animating && typeof getComputedStyle === 'function'
				? Number.parseFloat(getComputedStyle(g).opacity)
				: Number.NaN;
		g.classList.remove('xy-idle');
		if (!animating || !Number.isFinite(dip) || dip >= 1) {
			return;
		}
		if (typeof g.animate !== 'function') {
			return;
		}
		try {
			g.animate([{opacity: dip}, {opacity: 1}], {
				duration: 120,
				easing: 'ease-out',
			});
		} catch {
			/* 动画 API 被拒:退回瞬时常亮,可见性不受影响 */
		}
	};

	/** 运动后的节律:常亮起步,停手 560ms 转呼吸。打字、大跳、聚焦共用。 */
	const armIdle = (g: HTMLDivElement) => {
		wakeToFull(g);
		if (idleTimer.current) {
			clearTimeout(idleTimer.current);
		}
		idleTimer.current = setTimeout(() => {
			g.classList.remove('xy-moving');
			g.classList.add('xy-idle');
		}, IDLE_DELAY_MS);
	};

	const placeCaret = (mode: 'auto' | 'snap') => {
		const overlayEl = overlayRef.current;
		const innerEl = innerRef.current;
		const g = caretRef.current;
		if (!overlayEl || !g) {
			return;
		}
		/* 可见性不变量:光标只在 active && focused 时可见。滚动/重测这些入口
		   不受 React 依赖驱动,失焦后照样能打进来 —— 没有这道闸,失焦状态下
		   任何程序化 scroll(草稿切换、高度复位、贴底)都会把光标重新点亮,
		   用户读感就是"凭空闪一下"。 */
		if (!liveRef.current) {
			hideCaret(g);
			onShownRef.current = false;
			lastPosRef.current = null;
			return;
		}
		const parent = overlayEl.parentElement;
		if (!parent) {
			return;
		}

		/* 镜像滚动同步:textarea 滚动后内容反向平移。
		   只有 scrollTop 真的变了才写 style —— 写入本身会让整棵子树布局失效,
		   紧接着的 rect 读取就变成一次强制同步回流(打字时每键都踩)。 */
		if (!taElRef.current || !parent.contains(taElRef.current)) {
			taElRef.current =
				parent.querySelector<HTMLTextAreaElement>('textarea');
			/* 左右内边距随元素而定:换 textarea 才解析一次样式(这里的读写都在
			   按键关键路径上,不每键 getComputedStyle)。 */
			const el = taElRef.current;
			const cs = el ? getComputedStyle(el) : null;
			padRef.current = cs
				? (Number.parseFloat(cs.paddingLeft) || 0) +
					(Number.parseFloat(cs.paddingRight) || 0)
				: PAD_X * 2;
			appliedWidthRef.current = 0; /* 新元素:折行宽按需重写一次 */
		}
		const ta = taElRef.current;
		const shift = ta && ta.scrollTop > 0 ? ta.scrollTop : 0;
		if (innerEl && shift !== appliedShiftRef.current) {
			appliedShiftRef.current = shift;
			innerEl.style.transform = `translateY(${-shift}px)`;
		}

		/* 镜像折行宽 = textarea 内容宽。草稿涨到上限后 taAutoResize 打开 overflowY,
		   全局 ::-webkit-scrollbar(shell.css)在实机上让经典滚动条占掉内容宽 —— 镜像
		   若仍按整宽折行,折行点与 textarea 分叉,光标整字/整行错位。只在变了时写。 */
		if (ta && innerEl) {
			const contentW = Math.max(0, ta.clientWidth - padRef.current);
			if (contentW > 0 && contentW !== appliedWidthRef.current) {
				appliedWidthRef.current = contentW;
				innerEl.style.width = `${contentW}px`;
			}
		}

		const wrapRect = parent.getBoundingClientRect();
		const spans = readSpanView();
		const {cps, cpStarts} = readCps(value);
		/* caret(UTF-16)→ 目标 code point 边界:第一个起点 ≥ caret 的 cp */
		let nextCp = cpStarts.findIndex(s => s >= caret);
		if (nextCp === -1) {
			nextCp = cps.length;
		}

		let x: number;
		let y: number;
		if (spans.count === 0) {
			/* 空文本:零宽探针 span 给出与字符测量完全同系的几何(字体盒顶/内容
			 * 起点)。勿改回 PAD 常量——那与 span 路径差 ~3.5px,首字符会垂直
			 * 跳动并被误判 macro(2026-09-08 录屏实测)。坐标统一视口系。 */
			const probe = overlayEl.querySelector('span[data-probe]');
			const r = probe
				? probe.getBoundingClientRect()
				: null;
			x = r ? r.left : wrapRect.left + PAD_X;
			y = r ? r.top : wrapRect.top + PAD_Y;
		} else if (nextCp < spans.count) {
			const rNext = spans.at(nextCp)?.getBoundingClientRect();
			if (!rNext) {
				x = wrapRect.left + PAD_X;
				y = wrapRect.top + PAD_Y;
			} else if (nextCp > 0) {
				const rPrev = spans.at(nextCp - 1)?.getBoundingClientRect();
				if (rPrev && rNext.top > rPrev.top + 4) {
					x = rNext.left;   /* 跨行:行尾 → 下一行行首 */
					y = rNext.top;
				} else if (rPrev) {
					x = rPrev.right;
					y = rPrev.top;
				} else {
					x = rNext.left;
					y = rNext.top;
				}
			} else {
				x = rNext.left;
				y = rNext.top;
			}
		} else {
			/* 光标在文本末尾:先看尾哨兵(硬换行结尾才渲染),它给出下一行行首几何。
			 * 回退链保留 —— 空文本探针 / 无哨兵(软折行结尾)仍走最后一个码点右缘。 */
			const tailEl = endsWithHardNewline(cps)
				? overlayEl.querySelector('span[data-tail]')
				: null;
			const rTail = tailEl?.getBoundingClientRect();
			if (rTail) {
				x = rTail.left;
				y = rTail.top;
			} else {
				const rPrev = spans.at(spans.count - 1)?.getBoundingClientRect();
				x = rPrev ? rPrev.right : wrapRect.left + PAD_X;
				y = rPrev ? rPrev.top : wrapRect.top + PAD_Y;
			}
		}

		const tx = x - wrapRect.left;
		const ty = y - wrapRect.top - 2.5; /* 光标高 19 在行高 24 内居中(全路径同系) */
		g.classList.add('xy-on');

		/* 位置未变(如流式回复期间的父级重渲染):只保可见,不动节律 */
		const prev = lastPosRef.current;
		if (prev && onShownRef.current && prev.x === tx && prev.y === ty) {
			return;
		}
		lastPosRef.current = {x: tx, y: ty};

		/* 手势分级:单码点连续输入即便跨行也只滑移 —— 旧规则用"Δy ≥ 1 行"判 macro,
		   行尾打字挤到下一行时误判大跳,键盘手势下加 xy-moving(--xy-gcaret-h 24px),
		   读感就是"每打到行尾光标整根抽高再缩回"。 */
		const typedOne =
			mode !== 'snap' &&
			!!prev &&
			onShownRef.current &&
			isSingleCaretEdit(prevValueRef.current, value, caret);
		const kind =
			mode === 'snap' || !prev || !onShownRef.current
				? 'snap'
				: typedOne
					? 'fast'
					: Math.abs(ty - prev.y) < 1 &&
						  Math.abs(tx - prev.x) <= MICRO_MAX_DX
						? 'fast'
						: 'macro';
		onShownRef.current = true;

		g.classList.toggle('xy-snap', kind === 'snap');
		g.classList.toggle('xy-fast', kind === 'fast');
		/* 拉伸只属于键盘大跳的手势感(Home/End/PageUp…):鼠标点击同样是 macro
		 * 位移,但点击后光标"蹿高再缩回"读感就是 bug(2026-09-08 用户实测),
		 * 只滑移不拉伸。键盘性用 keydown 时间戳判定(点击不触发 keydown)。 */
		if (kind === 'macro' && performance.now() - recentKeyRef.current < 150) {
			g.classList.add('xy-moving');
		} else if (kind !== 'macro') {
			g.classList.remove('xy-moving'); /* fast 微移/snap 不拉伸:常态高 */
		}
		g.style.transform = `translate3d(${tx}px, ${ty}px, 0)`;

		/* snap(滚动/落位/重测)不搅动呼吸节律;打字/大跳 = 常亮 + 停手后呼吸 */
		if (kind === 'snap') {
			return;
		}
		armIdle(g);
	};

	/* 渲染驱动:值/光标/显隐变化后测量定位(layout effect 避免闪一帧) */
	useLayoutEffect(() => {
		if (active && focused) {
			placeCaret('auto');
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [value, caret, caretDir, active, focused, colorRanges, ghostHint]);

	/* 字符浮现(选型 C 字符部分,2026-09-08):新插入字符 3px 上浮+模糊消散。
	 * 命令式加类 + animationend 摘除——React 渲染不感知这类名,下一键不会
	 * 中途打断动画;类被着色重渲染覆盖(slash)时只是该字符动画静默,可接受。
	 * 粘贴/大段插入(>CH_IN_MAX_CP 个码点)跳过;IME 组词期间覆盖层卸载,
	 * 天然静默(提交的中文走 value diff,按普通插入浮现)。 */
	useLayoutEffect(() => {
		const pv = prevValueRef.current;
		prevValueRef.current = value;
		if (pv === value || !overlayRef.current) {
			return;
		}
		/* 公共前后缀 diff → 插入区间(UTF-16 闭开) */
		let p = 0;
		const maxP = Math.min(pv.length, value.length);
		while (p < maxP && pv[p] === value[p]) p++;
		let s = 0;
		const maxS = Math.min(pv.length, value.length) - p;
		while (s < maxS && pv[pv.length - 1 - s] === value[value.length - 1 - s]) s++;
		const insStart = p;
		const insEnd = value.length - s;
		if (insEnd <= insStart) {
			return; /* 纯删除:无动画 */
		}
		/* 先用缓存的 code point 表数出插入码点数（零 DOM），超阈值直接静默返回；
		   命中区间再按下标直取 span。原实现在同一个循环里对每个命中字符跑一次
		   querySelector 全子树扫描，粘贴大段插入时更是要先扫完再放弃。 */
		const {cps, cpStarts} = readCps(value);
		const hitIdx: number[] = [];
		for (let i = 0; i < cps.length; i++) {
			const start = cpStarts[i]!;
			if (start < insEnd && start + cps[i]!.length > insStart) {
				hitIdx.push(i);
				if (hitIdx.length > CH_IN_MAX_CP) {
					break;
				}
			}
		}
		if (hitIdx.length === 0 || hitIdx.length > CH_IN_MAX_CP) {
			return; /* 纯删除同帧 / 粘贴大段插入:静默 */
		}
		const spans = readSpanView();
		const targets: HTMLSpanElement[] = [];
		for (const i of hitIdx) {
			const el = spans.at(i);
			if (el) {
				targets.push(el);
			}
		}
		for (const el of targets) {
			if (!el.classList.contains('xy-ch-in')) {
				el.classList.add('xy-ch-in');
				el.addEventListener(
					'animationend',
					() => el.classList.remove('xy-ch-in'),
					{once: true},
				);
			}
		}
	}, [value]);

	/* 键盘手势标记:拉伸档只在 keydown 后 150ms 内生效,鼠标点击不触发
	 * keydown → 点击大跳只滑移不蹿高 */
	useLayoutEffect(() => {
		const parent = overlayRef.current?.parentElement;
		const ta = parent?.querySelector('textarea');
		if (!ta) {
			return;
		}
		const markKey = () => {
			recentKeyRef.current = performance.now();
		};
		ta.addEventListener('keydown', markKey);
		return () => ta.removeEventListener('keydown', markKey);
	}, [active]);

	/* 失焦 / 退场:清光全部类 → 基础 opacity:0 真隐没(CSS animation 会
	 * 压过基础声明,绝不能留 xy-idle,否则失焦后原地呼吸) */
	useLayoutEffect(() => {
		if (!active || !focused) {
			hideCaret(caretRef.current);
			onShownRef.current = false;
			lastPosRef.current = null;
			if (idleTimer.current) {
				clearTimeout(idleTimer.current);
			}
		}
	}, [active, focused]);

	/* 聚焦即起节律:落位本身走 snap(不搅动),但"停手 560ms 转呼吸"的计时
	   必须从可见那一刻开始 —— 否则聚焦后不打字的光标会一直常亮,与失焦前的
	   节律断裂(用户读感:同一件事一会儿闪一会儿不闪)。 */
	useLayoutEffect(() => {
		if (active && focused && caretRef.current) {
			armIdle(caretRef.current);
		}
	}, [active, focused]);

	/* 父级滚动同步出口:snap 档(镜像平移 + 位移瞬时)。
	   稳定外壳 + 每次渲染刷新内层实现:effect 依赖为空,不再每渲染重建对象。 */
	const placeCaretModeRef = useRef(placeCaret);
	placeCaretModeRef.current = placeCaret;

	/* 布局失效重量测:自动高度动画(逐帧重排)、分栏拖拽/窗口缩放(换行点变化)、
	   迟到字体(字形度量变化)都不改 value —— 没有这条链,光标就停在旧坐标,
	   直到下一次按键才跳回去。以 snap 档重定位:只对位移负责,不重启呼吸节律、
	   不触发拉伸。来源缺失(jsdom/老引擎)时 caretRemeasure 自动降级,不抛。 */
	useLayoutEffect(() => {
		if (!active) {
			return;
		}
		const overlayEl = overlayRef.current;
		if (!overlayEl) {
			return;
		}
		const remeasure = createCaretRemeasure(() => {
			if (liveRef.current) {
				placeCaretModeRef.current('snap');
			}
		});
		remeasure.attach(overlayEl.parentElement ?? overlayEl);
		return () => remeasure.dispose();
	}, [active]);
	const apiRefInner = useRef<TypingCaretApi>({
		reposition: () => placeCaretModeRef.current('snap'),
	});
	useLayoutEffect(() => {
		if (!apiRef) {
			return;
		}
		apiRef.current = apiRefInner.current;
		return () => {
			if (apiRef) {
				apiRef.current = null;
			}
		};
	}, [apiRef]);

	useEffectCleanup(idleTimer);

	/* 逐字符 span:UTF-16 → code point,着色区间按 UTF-16 相交判定。
	   code point 数组走 readCps 缓存（与 placeCaret 同一份,不重复拆串）。
	   元素表按「最长公共 code point 前缀」复用：前缀内每个 span 的 props 只由
	   该字符本身 + 它的 UTF-16 起点 + 着色区间决定,三者都在前缀里逐字相同,所以
	   可以原样交回同一批元素引用（React 对引用相同的元素不再建 work-in-progress）。
	   每键建表成本 O(全文) → O(变更后缀);着色区间变化（斜杠命令高亮）时整表重建。
	   渲染出的 DOM 与逐字符重建完全一致。 */
	const sameRanges = (
		a: {start: number; end: number}[],
		b: {start: number; end: number}[],
	) =>
		a.length === b.length &&
		a.every((r, i) => {
			const o = b[i];
			return !!o && r.start === o.start && r.end === o.end;
		});

	const buildCharNodes = (
		cps: string[],
		cpStarts: number[],
		ranges: {start: number; end: number}[],
	): ReactNode[] => {
		const colored = (u16Start: number, u16Len: number) =>
			ranges.some(r => u16Start < r.end && u16Start + u16Len > r.start);
		const cache = charNodesRef.current;
		let from = 0;
		let out: ReactNode[];
		if (cache && sameRanges(cache.ranges, ranges)) {
			if (cache.cps === cps) {
				/* value 未变（父级因别的原因重渲染）：整表原样交回 */
				return cache.nodes;
			}
			const prev = cache.cps;
			const n = Math.min(prev.length, cps.length);
			while (from < n && prev[from] === cps[from]) {
				from += 1;
			}
			out = cache.nodes.slice(0, from);
		} else {
			out = [];
		}
		for (let i = from; i < cps.length; i += 1) {
			const ch = cps[i]!;
			out.push(
				<span
					key={i}
					data-ci={i}
					className={
						colored(cpStarts[i]!, ch.length) ? 'text-accent' : undefined
					}
				>
					{ch}
				</span>,
			);
		}
		charNodesRef.current = {cps, ranges, nodes: out};
		return out;
	};

	if (!active) {
		return null;
	}

	const {cps, cpStarts} = readCps(value);
	const nodes = buildCharNodes(cps, cpStarts, colorRanges);
	const hardNewlineTail = endsWithHardNewline(cps);

	return (
		<>
			<div
				ref={overlayRef}
				aria-hidden
				className="pointer-events-none absolute inset-0 z-[4] overflow-hidden px-3 pt-3"
			>
				{/* inner 层承担 translateY(-scrollTop) 滚动镜像,外层只做裁剪 */}
				<div
					ref={innerRef}
					className="whitespace-pre-wrap break-words font-sans text-[14px] leading-6 text-ink"
				>
					{cps.length === 0 ? (
						/* 空文本测量探针:零宽,几何与真实字符同系(字体盒顶/内容起点) */
						<span data-probe>{'\u200b'}</span>
					) : null}
					{nodes}
					{/* 尾哨兵:文本以硬换行结尾时占位。硬换行后 Chromium 不单独生成行盒,
					    最后一个 '\n' span 的 rect 仍留在上一行 —— 直接用它锚光标就是
					    "换行不动"。零宽哨兵落在下一行行首(真实 Chrome 实测:内容左缘、
					    下一行 rowTop),同时让镜像行数与 textarea 行数对齐。 */}
					{hardNewlineTail ? <span data-tail>{'\u200b'}</span> : null}
					{ghostHint ? (
						<span data-ghost className="select-none pl-1 text-ink/40">
							{ghostHint}
						</span>
					) : null}
				</div>
			</div>
			<div ref={caretRef} aria-hidden className="xy-gcaret" />
		</>
	);
}

/** 文本是否以硬换行结尾(仅 '\n' 计硬换行;软折行由排版决定,引擎不推测) */
export function endsWithHardNewline(cps: readonly string[]): boolean {
	return cps.length > 0 && cps[cps.length - 1] === '\n';
}

/** 卸载时清呼吸定时器(独立小 hook,避免主 effect 依赖膨胀) */
function useEffectCleanup(timer: {current: ReturnType<typeof setTimeout> | null}) {
	useLayoutEffect(() => {
		return () => {
			if (timer.current) {
				clearTimeout(timer.current);
			}
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);
}
