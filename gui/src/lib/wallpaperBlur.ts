/** 壁纸离屏降采样再模糊：小图画糊再 stretch，避免全视口实时 filter。 */

const BLUR_DOWNSAMPLE_THRESHOLD = 12;
const MAX_BLUR_PX = 40;
const MAX_EDGE_PX = 960;

function loadImage(src: string): Promise<HTMLImageElement> {
	return new Promise((resolve, reject) => {
		const img = new Image();
		img.decoding = 'async';
		img.onload = () => resolve(img);
		img.onerror = () => reject(new Error('wallpaper load failed'));
		img.src = src;
	});
}

/**
 * @param src 壁纸 URL（含 data:）
 * @param blurPx 用户设定 0–40
 * @param signal 取消用
 * @returns 已烘焙模糊的 data URL；blur≈0 时直接返回原 src
 */
export async function bakeWallpaperBlur(
	src: string,
	blurPx: number,
	signal?: AbortSignal,
): Promise<string> {
	const blur = Math.min(MAX_BLUR_PX, Math.max(0, blurPx));
	if (blur < 0.5) {
		return src;
	}
	if (signal?.aborted) {
		throw new DOMException('aborted', 'AbortError');
	}

	const img = await loadImage(src);
	if (signal?.aborted) {
		throw new DOMException('aborted', 'AbortError');
	}

	const iw = Math.max(1, img.naturalWidth || img.width);
	const ih = Math.max(1, img.naturalHeight || img.height);
	/* blur>12 降采样：半径越大画布越小，stretch 后视觉糊度接近全尺寸 blur */
	const scale =
		blur > BLUR_DOWNSAMPLE_THRESHOLD
			? Math.min(1, BLUR_DOWNSAMPLE_THRESHOLD / blur)
			: 1;
	let tw = Math.max(1, Math.round(iw * scale));
	let th = Math.max(1, Math.round(ih * scale));
	const edge = Math.max(tw, th);
	if (edge > MAX_EDGE_PX) {
		const fit = MAX_EDGE_PX / edge;
		tw = Math.max(1, Math.round(tw * fit));
		th = Math.max(1, Math.round(th * fit));
	}

	const canvas = document.createElement('canvas');
	canvas.width = tw;
	canvas.height = th;
	const ctx = canvas.getContext('2d');
	if (!ctx) {
		return src;
	}

	const pad = Math.ceil(blur * scale) + 2;
	ctx.filter = `blur(${Math.max(0.5, blur * (tw / iw))}px)`;
	ctx.drawImage(img, -pad, -pad, tw + pad * 2, th + pad * 2);

	if (signal?.aborted) {
		throw new DOMException('aborted', 'AbortError');
	}

	try {
		return canvas.toDataURL('image/jpeg', 0.82);
	} catch {
		return src;
	}
}

export function effectiveWallpaperBlurCap(blurPx: number): number {
	const blur = Math.min(MAX_BLUR_PX, Math.max(0, blurPx));
	if (
		typeof window !== 'undefined' &&
		window.matchMedia('(prefers-reduced-motion: reduce)').matches
	) {
		return Math.min(blur, 8);
	}
	return blur;
}
