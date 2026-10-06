/**
 * 会话切换覆盖层：滞后窗口（stores/chat/switchLag）亮着时盖住消息区，
 * 视觉沿用冷会话等待骨架的沉底脉冲条（MessageList.SessionPendingState）。
 * 只负责画：滞后时序在 switchLag，落点逻辑不受影响。
 *
 * 开壁纸时不能盖不透明纸面：消息区是半透的（壁纸从 L0 透上来），纸面一盖就是
 * 肉眼可见的一闪。这里改成复刻 L0（与吸顶 pin 同一套 --xy-bg-* 层源），
 * 背景位置按覆盖层自身原点平移，逐像素对齐壁纸绘制矩形。
 */
import {useLayoutEffect, useRef} from 'react';
import {readBgDrawPos} from '@/components/sticky/stickyGeometry';
import {useSwitchLag} from '@/stores/chat/switchLag';

export function SwitchCover() {
	const {lagging} = useSwitchLag();
	const ref = useRef<HTMLDivElement>(null);
	useLayoutEffect(() => {
		if (!lagging) {
			return;
		}
		const el = ref.current;
		if (!el || !el.closest('[data-review-wallpaper="1"]')) {
			return;
		}
		const rect = el.getBoundingClientRect();
		const draw = readBgDrawPos(el);
		/* 三值列表：两张渐变铺满（0 0），只有壁纸层按「绘制原点 − 覆盖层原点」平移。
		   写成单个位置会被三层共用，把渐变一起推走 → 覆盖层露出未压色的原图。 */
		el.style.backgroundPosition = `0 0, 0 0, ${Math.round(draw.x - rect.x)}px ${Math.round(draw.y - rect.y)}px`;
	}, [lagging]);
	if (!lagging) {
		return null;
	}
	return (
		<div
			ref={ref}
			className="xy-switch-cover pointer-events-none absolute inset-0 z-30 flex min-h-0 flex-col bg-paper"
			aria-busy="true"
		>
			<div className="flex min-h-0 flex-1 flex-col justify-end gap-2.5 overflow-hidden px-3 pb-10 sm:px-5 md:px-8">
				<div className="h-9 w-2/3 animate-pulse self-end rounded-2xl bg-ink/[0.06]" />
				<div className="h-4 w-3/5 animate-pulse rounded-full bg-ink/[0.04]" />
				<div className="h-4 w-4/5 animate-pulse rounded-full bg-ink/[0.04]" />
			</div>
			<span className="sr-only">正在切换对话…</span>
		</div>
	);
}
