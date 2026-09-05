/** 背景图：允许选择大图，存储压缩后的桌面尺寸 JPEG。 */

export const BG_PICK_MAX_BYTES = 10 * 1024 * 1024;
/** 缩放后最长边 — 足以覆盖多数显示器，模糊开销低。 */
const MAX_EDGE = 1920;
/** 目标存储 data-URL 大小（base64）；保持 localStorage/IDB 轻量。 */
const TARGET_DATA_URL_BYTES = 1.2 * 1024 * 1024;

function loadImage(file: File): Promise<HTMLImageElement> {
	return new Promise((resolve, reject) => {
		const url = URL.createObjectURL(file);
		const img = new Image();
		img.onload = () => {
			URL.revokeObjectURL(url);
			resolve(img);
		};
		img.onerror = () => {
			URL.revokeObjectURL(url);
			reject(new Error('无法读取图片'));
		};
		img.src = url;
	});
}

function canvasToJpeg(
	canvas: HTMLCanvasElement,
	quality: number,
): Promise<string> {
	return new Promise((resolve, reject) => {
		canvas.toBlob(
			blob => {
				if (!blob) {
					reject(new Error('图片压缩失败'));
					return;
				}
				const reader = new FileReader();
				reader.onload = () => {
					if (typeof reader.result === 'string') {
						resolve(reader.result);
					} else {
						reject(new Error('图片编码失败'));
					}
				};
				reader.onerror = () => reject(new Error('图片编码失败'));
				reader.readAsDataURL(blob);
			},
			'image/jpeg',
			quality,
		);
	});
}

/**
 * 缩小 + JPEG 压缩，使 10MB 选择变为约 0.5–1.2MB 存储。
 * 照片优先 JPEG 而非 PNG；保持模糊/透明度 UI 流畅。
 */
export async function compressBackgroundImage(file: File): Promise<string> {
	const img = await loadImage(file);
	const scale = Math.min(1, MAX_EDGE / Math.max(img.width, img.height));
	const w = Math.max(1, Math.round(img.width * scale));
	const h = Math.max(1, Math.round(img.height * scale));

	const canvas = document.createElement('canvas');
	canvas.width = w;
	canvas.height = h;
	const ctx = canvas.getContext('2d');
	if (!ctx) {
		throw new Error('无法压缩图片');
	}
	ctx.fillStyle = '#f3f1ec';
	ctx.fillRect(0, 0, w, h);
	ctx.drawImage(img, 0, 0, w, h);

	let quality = 0.84;
	let dataUrl = await canvasToJpeg(canvas, quality);
	while (dataUrl.length > TARGET_DATA_URL_BYTES && quality > 0.45) {
		quality -= 0.1;
		dataUrl = await canvasToJpeg(canvas, quality);
	}
	return dataUrl;
}
