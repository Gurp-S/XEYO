import {useLayoutEffect, useRef, type ReactNode} from 'react';

/**
 * 自绘光标 + 镜像覆盖层(2026-09-08,选型「3 · macOS 弹性微过冲」白色版)。
 *
 * 结构:textarea 文字 text-transparent,本组件逐字符渲染镜像文本并放一个
 * 自绘光标 div(150ms 弹性微过冲滑移,移动拉伸,停手柔和呼吸)。
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
 * - active=false(IME 组词 / 超大文本)→ 整层不渲染,退回原生光标;
 * - 失焦隐没,聚焦浮现;滚动由父级调 apiRef.reposition() 重测视觉坐标。
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
	/** 父级在 textarea scroll / 程序化 setSelectionRange 后调用,仅重测位置 */
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
	const caretRef = useRef<HTMLDivElement>(null);
	const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

	const placeCaret = () => {
		const overlayEl = overlayRef.current;
		const g = caretRef.current;
		if (!overlayEl || !g) {
			return;
		}
		const parent = overlayEl.parentElement;
		if (!parent) {
			return;
		}
		const wrapRect = parent.getBoundingClientRect();
		const spanEls = Array.from(
			overlayEl.querySelectorAll<HTMLSpanElement>('span[data-ci]'),
		);
		const cps = Array.from(value);
		/* caret(UTF-16)→ 目标 code point 边界:第一个起点 ≥ caret 的 cp */
		const cpStarts: number[] = [];
		let u16 = 0;
		for (const ch of cps) {
			cpStarts.push(u16);
			u16 += ch.length;
		}
		let nextCp = cpStarts.findIndex(s => s >= caret);
		if (nextCp === -1) {
			nextCp = cps.length;
		}

		let x: number;
		let y: number;
		let empty = false;
		if (spanEls.length === 0) {
			/* 空文本:光标落内容起点,坐标已是 wrap 局部系,不再减 wrapRect */
			x = PAD_X;
			y = PAD_Y;
			empty = true;
		} else if (nextCp < spanEls.length) {
			const rNext = spanEls[nextCp].getBoundingClientRect();
			if (nextCp > 0) {
				const rPrev = spanEls[nextCp - 1].getBoundingClientRect();
				if (rNext.top > rPrev.top + 4) {
					x = rNext.left;   /* 跨行:行尾 → 下一行行首 */
					y = rNext.top;
				} else {
					x = rPrev.right;
					y = rPrev.top;
				}
			} else {
				x = rNext.left;
				y = rNext.top;
			}
		} else {
			const rPrev = spanEls[spanEls.length - 1].getBoundingClientRect();
			x = rPrev.right;
			y = rPrev.top;
		}

		const tx = empty ? x : x - wrapRect.left;
		const ty = (empty ? y : y - wrapRect.top) - 2.5; /* 光标高 19 在行高 24 内居中 */
		g.style.transform = `translate3d(${tx}px, ${ty}px, 0)`;
		g.classList.add('xy-on', 'xy-moving');
		g.classList.remove('xy-idle');
		if (idleTimer.current) {
			clearTimeout(idleTimer.current);
		}
		idleTimer.current = setTimeout(() => {
			g.classList.remove('xy-moving');
			g.classList.add('xy-idle');
		}, IDLE_DELAY_MS);
	};

	/* 渲染驱动:值/光标/显隐变化后测量定位(layout effect 避免闪一帧) */
	useLayoutEffect(() => {
		if (active && focused) {
			placeCaret();
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [value, caret, caretDir, active, focused, colorRanges, ghostHint]);

	/* 失焦 / 退场:光标隐没 */
	useLayoutEffect(() => {
		if (!active || !focused) {
			const g = caretRef.current;
			if (g) {
				g.classList.remove('xy-on', 'xy-moving');
				g.classList.add('xy-idle');
			}
		}
	}, [active, focused]);

	/* 父级滚动同步出口 */
	useLayoutEffect(() => {
		if (apiRef) {
			apiRef.current = {reposition: placeCaret};
		}
		return () => {
			if (apiRef) {
				apiRef.current = null;
			}
		};
	});

	useEffectCleanup(idleTimer);

	if (!active) {
		return null;
	}

	/* 逐字符 span:UTF-16 → code point,着色区间按 UTF-16 相交判定 */
	const isColored = (u16Start: number, u16Len: number) =>
		colorRanges.some(r => u16Start < r.end && u16Start + u16Len > r.start);

	const cps = Array.from(value);
	let u16 = 0;
	const nodes: ReactNode[] = cps.map((ch, i) => {
		const start = u16;
		u16 += ch.length;
		return (
			<span
				key={i}
				data-ci={i}
				className={isColored(start, ch.length) ? 'text-accent' : undefined}
			>
				{ch}
			</span>
		);
	});

	return (
		<>
			<div
				ref={overlayRef}
				aria-hidden
				className="pointer-events-none absolute inset-0 z-[4] overflow-hidden whitespace-pre-wrap break-words px-3 pt-3 font-sans text-[14px] leading-6 text-ink [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
			>
				{nodes}
				{ghostHint ? (
					<span data-ghost className="select-none text-ink/40">
						{ghostHint}
					</span>
				) : null}
			</div>
			<div ref={caretRef} aria-hidden className="xy-gcaret" />
		</>
	);
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
