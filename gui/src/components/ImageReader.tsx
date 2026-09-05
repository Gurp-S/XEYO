import {useEffect, useId, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {RotateCcw, X, ZoomIn, ZoomOut} from 'lucide-react';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {cn} from '@/lib/utils';

export type ImageReaderSource = {
	src: string;
	alt?: string;
	title?: string;
};

type ImageReaderDialogProps = {
	image: ImageReaderSource | null;
	onClose: () => void;
};

const MIN_ZOOM = 1;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.25;

function clampZoom(value: number): number {
	return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value.toFixed(2))));
}

/**
 * Shared Markdown-style image reader.
 *
 * The dialog is portalled to body so it is not clipped by chat scrollers,
 * sticky surfaces, or local stacking contexts. The image and close control
 * intentionally live in separate elements so the preview remains a readable
 * panel rather than a full-screen button.
 */
export function ImageReaderDialog({image, onClose}: ImageReaderDialogProps) {
	const titleId = useId();
	const closeButtonRef = useRef<HTMLButtonElement>(null);
	const onCloseRef = useRef(onClose);
	onCloseRef.current = onClose;
	const [zoom, setZoom] = useState(MIN_ZOOM);

	useEffect(() => {
		if (!image) {
			return;
		}

		setZoom(MIN_ZOOM);
		const previousOverflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === '+' || event.key === '=') {
				event.preventDefault();
				setZoom(value => clampZoom(value + ZOOM_STEP));
				return;
			}
			if (event.key === '-') {
				event.preventDefault();
				setZoom(value => clampZoom(value - ZOOM_STEP));
				return;
			}
			if (event.key === '0') {
				event.preventDefault();
				setZoom(MIN_ZOOM);
			}
		};
		pushEscLayer('image-reader', () => onCloseRef.current());
		window.addEventListener('keydown', handleKeyDown);
		const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());

		return () => {
			popEscLayer('image-reader');
			window.cancelAnimationFrame(focusFrame);
			window.removeEventListener('keydown', handleKeyDown);
			document.body.style.overflow = previousOverflow;
		};
		}, [image?.src]);

	if (!image || typeof document === 'undefined') {
		return null;
	}

	const title = image.title || image.alt || '图片预览';
	const dialog = (
		<div
			className="fixed inset-0 z-[160] flex items-center justify-center bg-black/45 p-3 backdrop-blur-[3px] sm:p-6"
			role="presentation"
			onMouseDown={event => {
				if (event.target === event.currentTarget) {
					onClose();
				}
			}}
		>
			<div
				role="dialog"
				aria-modal="true"
				aria-labelledby={titleId}
				className="flex h-[min(88dvh,48rem)] w-[min(94vw,64rem)] min-w-0 flex-col overflow-hidden rounded-2xl border border-line/60 bg-paper/95 shadow-2xl shadow-ink/20"
				onMouseDown={event => event.stopPropagation()}
			>
				<header className="flex shrink-0 items-center justify-between gap-3 border-b border-line/45 px-3.5 py-2.5 sm:px-4">
					<div className="min-w-0">
						<p id={titleId} className="truncate font-sans text-[13px] font-medium text-ink">
							{title}
						</p>
						<p className="mt-0.5 font-mono text-[10px] tracking-wide text-mute">
							{Math.round(zoom * 100)}% · 滚轮或 +/- 调整
						</p>
					</div>
					<div className="flex shrink-0 items-center gap-1">
						<button
							type="button"
							onClick={() => setZoom(value => clampZoom(value - ZOOM_STEP))}
							disabled={zoom <= MIN_ZOOM}
							aria-label="缩小图片"
							className="xy-icon-btn flex h-8 w-8 items-center justify-center rounded-full text-mute transition-[background-color,color,opacity] duration-150 hover:bg-ink/[0.06] hover:text-ink disabled:pointer-events-none disabled:opacity-35"
						>
							<ZoomOut className="h-4 w-4" strokeWidth={1.8} />
						</button>
						<button
							type="button"
							onClick={() => setZoom(MIN_ZOOM)}
							disabled={zoom === MIN_ZOOM}
							aria-label="还原图片大小"
							className="xy-icon-btn flex h-8 w-8 items-center justify-center rounded-full text-mute transition-[background-color,color,opacity] duration-150 hover:bg-ink/[0.06] hover:text-ink disabled:pointer-events-none disabled:opacity-35"
						>
							<RotateCcw className="h-3.5 w-3.5" strokeWidth={1.8} />
						</button>
						<button
							type="button"
							onClick={() => setZoom(value => clampZoom(value + ZOOM_STEP))}
							disabled={zoom >= MAX_ZOOM}
							aria-label="放大图片"
							className="xy-icon-btn flex h-8 w-8 items-center justify-center rounded-full text-mute transition-[background-color,color,opacity] duration-150 hover:bg-ink/[0.06] hover:text-ink disabled:pointer-events-none disabled:opacity-35"
						>
							<ZoomIn className="h-4 w-4" strokeWidth={1.8} />
						</button>
						<span className="mx-1 h-4 w-px bg-line/50" aria-hidden />
						<button
							ref={closeButtonRef}
							type="button"
							onClick={onClose}
							aria-label="关闭图片预览"
							className="xy-icon-btn flex h-8 w-8 items-center justify-center rounded-full text-mute transition-[background-color,color] duration-150 hover:bg-ink/[0.08] hover:text-ink"
						>
							<X className="h-4 w-4" strokeWidth={1.8} />
						</button>
					</div>
				</header>

				<div
					className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-paper-deep/20 p-4 sm:p-8"
					onWheel={event => {
						event.preventDefault();
						setZoom(value => clampZoom(value + (event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP)));
					}}
				>
					<div className="flex min-h-full min-w-full items-center justify-center">
						<img
							src={image.src}
							alt={image.alt || title}
							draggable={false}
							className={cn(
								'block max-h-[calc(88dvh-10rem)] max-w-full rounded-xl border border-line/50 bg-paper/70 object-contain shadow-lg shadow-ink/10 transition-transform duration-150',
								zoom > MIN_ZOOM && 'cursor-zoom-out',
							)}
							style={{transform: `scale(${zoom})`}}
							onClick={event => event.stopPropagation()}
						/>
					</div>
				</div>
			</div>
		</div>
	);

	return createPortal(dialog, document.body);
}
