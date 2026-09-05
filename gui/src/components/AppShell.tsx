import {useEffect, useState, type CSSProperties, type ReactNode} from 'react';
import {
	bindReducedMotionToSmoothness,
	useSettingsStore,
} from '@/stores/settingsStore';
import {useShallow} from 'zustand/react/shallow';
import {
	bakeWallpaperBlur,
	effectiveWallpaperBlurCap,
} from '@/lib/wallpaperBlur';
import {syncPromptViewCapVar} from '@/components/sticky/stickyTypes';
import {TitleBar} from './TitleBar';
import {WindowResizeHandles} from './WindowResizeHandles';
import {ContextIsland} from '@/pasture/ContextIsland';

type Props = {
	children: ReactNode;
};

/**
 * bgOpacity 0–100:
 * - 100 → 壁纸完全可见，遮罩 ≈ 0
 * - 0   → 壁纸不可见，实心纸质感遮罩
 *
 * 玻璃色透明度随 bgOpacity 联动：壁纸越淡，玻璃越实。
 * veil 用当前主题 --xy-paper，避免硬编码昼夜 RGB。
 */
function wallpaperAndVeil(opacityPct: number) {
	const t = Math.min(100, Math.max(0, opacityPct)) / 100;
	const wallpaperOpacity = t;
	// 线性覆盖：0% → 不透明纸面，100% → 无遮罩
	const veil = 1 - t;
	const veilColor = `color-mix(in oklch, var(--xy-paper) ${Math.round(veil * 100)}%, transparent)`;
	// 玻璃色透明度：壁纸越淡，玻璃越实（保留 50% 玻璃感）
	const gf = 0.5;
	const glassAlpha = +(0.55 + (1 - t) * (1 - 0.55) * gf).toFixed(3);
	const glassHoverAlpha = +(0.62 + (1 - t) * (1 - 0.62) * gf).toFixed(3);
	const glassStrongAlpha = +(0.82 + (1 - t) * (1 - 0.82) * gf).toFixed(3);
	const glassSoftAlpha = +(0.4 + (1 - t) * (1 - 0.4) * gf).toFixed(3);
	/* L0 实际合成：img(α=t) 再叠 veil(paper, α=1-t) → 等效 img 可见度 t²。
	   自绘壁纸 pin（阶段1）按该合成值复刻，保证与透出的 L0 像素一致。 */
	const veilComposited = `color-mix(in oklch, var(--xy-paper) ${Math.round((1 - t * t) * 100)}%, transparent)`;
	return {
		wallpaperOpacity,
		veilColor,
		veilComposited,
		showVeil: veil > 0.001,
		glassAlpha,
		glassHoverAlpha,
		glassStrongAlpha,
		glassSoftAlpha,
	};
}

export function AppShell({children}: Props) {
	const {bgImage, bgOpacity, bgBlur} = useSettingsStore(
		useShallow(s => ({
			bgImage: s.bgImage,
			bgOpacity: s.bgOpacity,
			bgBlur: s.bgBlur,
		})),
	);
	const showWallpaper = Boolean(bgImage);
	const {wallpaperOpacity, veilColor, veilComposited, showVeil} =
		wallpaperAndVeil(bgOpacity);
	const cappedBlur = effectiveWallpaperBlurCap(bgBlur);
	const [bakedSrc, setBakedSrc] = useState<string | null>(null);
	/* L0 壁纸实际绘制矩形（cover×1.04、视口居中，px）。自绘壁纸 pin 用它做逐像素
	   对齐的 background-position/size；仅在图片加载与窗口 resize 时重算，不进滚动帧。 */
	const [bgDraw, setBgDraw] = useState<{
		w: number;
		h: number;
		x: number;
		y: number;
	} | null>(null);

	useEffect(() => {
		if (!bgImage) {
			setBakedSrc(null);
			return;
		}
		if (cappedBlur < 0.5) {
			setBakedSrc(bgImage);
			return;
		}
		const ac = new AbortController();
		let cancelled = false;
		void bakeWallpaperBlur(bgImage, cappedBlur, ac.signal)
			.then(url => {
				if (!cancelled) {
					setBakedSrc(url);
				}
			})
			.catch(() => {
				if (!cancelled) {
					setBakedSrc(bgImage);
				}
			});
		return () => {
			cancelled = true;
			ac.abort();
		};
	}, [bgImage, cappedBlur]);

	useEffect(() => {
		return bindReducedMotionToSmoothness(
			() => useSettingsStore.getState().smoothness !== false,
		);
	}, []);

	/* 查看/编辑统一高度上限的 CSS var（--xy-prompt-view-cap）：
	   挂载 + 窗口 resize 时重写，使 .xy-editing-bubble 与 pin 内联 max-height 同源。
	   var 改值会自动触发两端样式重算，无需等 sticky flush。 */
	useEffect(() => {
		syncPromptViewCapVar();
		const onResize = () => syncPromptViewCapVar();
		window.addEventListener('resize', onResize);
		window.addEventListener('orientationchange', onResize);
		return () => {
			window.removeEventListener('resize', onResize);
			window.removeEventListener('orientationchange', onResize);
		};
	}, []);

	const layerSrc = bakedSrc ?? bgImage;

	/* 见 bgDraw 注释：绘制矩形随图片加载 / 窗口尺寸更新。 */
	useEffect(() => {
		if (!showWallpaper || !layerSrc) {
			setBgDraw(null);
			return;
		}
		let cancelled = false;
		let onResize: (() => void) | null = null;
		const img = new Image();
		img.onload = () => {
			if (cancelled) {
				return;
			}
			const update = () => {
				const vw = window.innerWidth;
				const vh = window.innerHeight;
				if (!vw || !vh) {
					return;
				}
				const iw = img.naturalWidth || 1;
				const ih = img.naturalHeight || 1;
				const scale = 1.04 * Math.max(vw / iw, vh / ih);
				const w = iw * scale;
				const h = ih * scale;
				setBgDraw({w, h, x: (vw - w) / 2, y: (vh - h) / 2});
			};
			update();
			onResize = update;
			window.addEventListener('resize', update);
		};
		img.src = layerSrc;
		return () => {
			cancelled = true;
			if (onResize) {
				window.removeEventListener('resize', onResize);
			}
		};
	}, [layerSrc, showWallpaper]);

	return (
		<div className="relative h-full w-full min-h-0 min-w-0">
			<div
				className="relative z-0 flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden bg-paper"
				style={
					{
						['--xy-bg-image' as string]: showWallpaper
							? `url(${layerSrc})`
							: 'none',
						['--xy-bg-wallpaper-opacity' as string]: String(
							showWallpaper ? wallpaperOpacity : 0,
						),
						['--xy-bg-blur' as string]: `${cappedBlur}px`,
						['--xy-bg-veil' as string]: showWallpaper
							? veilColor
							: 'var(--xy-paper)',
						/* 自绘壁纸 pin（阶段1）消费：合成 veil 与壁纸实际绘制矩形 */
						['--xy-bg-veil-composited' as string]:
							showWallpaper ? veilComposited : 'var(--xy-paper)',
						['--xy-bg-draw-size' as string]: bgDraw
							? `${bgDraw.w}px ${bgDraw.h}px`
							: '0px 0px',
						['--xy-bg-draw-pos' as string]: bgDraw
							? `${bgDraw.x}px ${bgDraw.y}px`
							: '0px 0px',
					} as CSSProperties
				}
			>
				{showWallpaper && layerSrc ? (
					<div
						aria-hidden
						className="xy-bg-layer pointer-events-none absolute inset-0 z-0"
						style={{
							backgroundImage: `url(${layerSrc})`,
							backgroundSize: 'cover',
							backgroundPosition: 'center',
							opacity: wallpaperOpacity,
							/* 模糊已离屏烘焙；仅在烘焙完成前短暂用 CSS blur 兜底 */
							filter:
								bakedSrc && bakedSrc !== bgImage
									? undefined
									: cappedBlur > 0.5
										? `blur(${cappedBlur}px)`
										: undefined,
							transform: 'scale(1.04)',
						}}
					/>
				) : null}
				{showWallpaper && showVeil ? (
					<div
						aria-hidden
						className="pointer-events-none absolute inset-0 z-0"
						style={{background: veilColor}}
					/>
				) : null}

				<div className="relative z-10 flex min-h-0 min-w-0 flex-1 flex-col bg-transparent">
					<TitleBar />
					<div className="relative z-0 flex min-h-0 min-w-0 flex-1 flex-col">
						{children}
						<WindowResizeHandles />
					</div>
				</div>
				<ContextIsland />
			</div>
		</div>
	);
}
