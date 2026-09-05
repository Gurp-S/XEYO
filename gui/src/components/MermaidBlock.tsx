import {Expand, RotateCcw, X, ZoomIn, ZoomOut} from 'lucide-react';
import {memo, useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import {
	getCachedMermaidSvg,
	renderMermaidSvg,
	svgToImageUrl,
} from '@/lib/mermaidRender';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';
import {useSettingsStore} from '@/stores/settingsStore';
import {isDarkScheme} from '@/theme/catalog';
import {CodeBlock} from './CodeBlock';

type Props = {
	source: string;
};

const SCALE_MIN = 0.25;
const SCALE_MAX = 8;

function clampScale(n: number): number {
	return Math.min(SCALE_MAX, Math.max(SCALE_MIN, n));
}

function MermaidBlockInner({source}: Props) {
	const theme = useSettingsStore(s => s.theme);
	const mermaidTheme = isDarkScheme(theme) ? 'dark' : 'default';
	const text = source.trim();
	const [url, setUrl] = useState<string | null>(() => {
		const cached = getCachedMermaidSvg(text, mermaidTheme);
		return cached ? svgToImageUrl(cached) : null;
	});
	const [failed, setFailed] = useState(false);
	// 失败原因透传（P1-⑥：mermaid 不渲染时给出可诊断提示，区分 import/wasm 失败 vs 语法失败）。
	const [failReason, setFailReason] = useState<string | null>(null);
	const [open, setOpen] = useState(false);
	const [scale, setScale] = useState(1);

	useEffect(() => {
		if (!text) {
			setUrl(null);
			setFailed(false);
			setFailReason(null);
			return;
		}
		const cached = getCachedMermaidSvg(text, mermaidTheme);
		if (cached) {
			setUrl(svgToImageUrl(cached));
			setFailed(false);
			setFailReason(null);
			return;
		}
		let alive = true;
		setFailed(false);
		setFailReason(null);
		void renderMermaidSvg(text, mermaidTheme)
			.then(svg => {
				if (alive) {
					setUrl(svgToImageUrl(svg));
				}
			})
			.catch((err: unknown) => {
				if (alive) {
					setFailed(true);
					setUrl(null);
					setFailReason(
						err instanceof Error ? err.message : String(err),
					);
				}
			});
		return () => {
			alive = false;
		};
	}, [text, mermaidTheme]);

	useEffect(() => {
		if (!open) {
			return;
		}
		const prev = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		pushEscLayer('mermaid-viewer', () => setOpen(false));
		const onWheel = (e: WheelEvent) => {
			e.preventDefault();
			setScale(s => clampScale(s * (e.deltaY > 0 ? 1 / 1.12 : 1.12)));
		};
		window.addEventListener('wheel', onWheel, {passive: false});
		return () => {
			document.body.style.overflow = prev;
			popEscLayer('mermaid-viewer');
			window.removeEventListener('wheel', onWheel);
		};
	}, [open]);

	const zoomBy = (factor: number) => {
		setScale(s => clampScale(s * factor));
	};

	if (failed) {
		return (
			<div className="my-1.5">
				<p className="mb-1 text-[12px] text-mute">
					图表生成失败
					{failReason ? `：${failReason}` : ''}，已展示源码。
				</p>
				<CodeBlock language="mermaid" value={source} autoCollapse={false} />
			</div>
		);
	}
	if (!url) {
		return <p className="my-1.5 text-[13px] text-mute">图表生成中…</p>;
	}
	return (
		<>
			<div className="group relative my-2 w-full">
				<img
					src={url}
					alt="mermaid"
					className="h-auto max-w-full"
				/>
				<button
					type="button"
					title="放大查看"
					aria-label="放大查看"
					className="xy-hover-reveal absolute top-1.5 right-1.5 rounded-md bg-ink/55 p-1 text-paper opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 hover:bg-ink/75"
					onClick={() => {
						setScale(1);
						setOpen(true);
					}}
				>
					<Expand className="h-3.5 w-3.5" />
				</button>
			</div>
			{open
				? createPortal(
						<div className="fixed inset-0 z-[80] bg-[#1a1d21]">
							<div className="absolute top-3 right-3 z-10 flex items-center gap-1 rounded-lg bg-glass-strong p-1">
								<button
									type="button"
									className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
									title="放大"
									aria-label="放大"
									onClick={() => zoomBy(1.2)}
								>
									<ZoomIn className="h-4 w-4" />
								</button>
								<button
									type="button"
									className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
									title="缩小"
									aria-label="缩小"
									onClick={() => zoomBy(1 / 1.2)}
								>
									<ZoomOut className="h-4 w-4" />
								</button>
								<button
									type="button"
									className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
									title="复位"
									aria-label="复位"
									onClick={() => setScale(1)}
								>
									<RotateCcw className="h-4 w-4" />
								</button>
								<button
									type="button"
									className="xy-icon-btn rounded-md p-1.5 text-mute hover:bg-glass-hover hover:text-ink"
									title="关闭"
									aria-label="关闭"
									onClick={() => setOpen(false)}
								>
									<X className="h-4 w-4" />
								</button>
							</div>
							<div className="flex h-full w-full items-center justify-center overflow-hidden p-8">
								<img
									src={url}
									alt="mermaid"
									draggable={false}
									style={{
										transform: `scale(${scale})`,
										transformOrigin: 'center center',
									}}
									className="max-h-full max-w-full object-contain"
								/>
							</div>
						</div>,
						document.body,
					)
				: null}
		</>
	);
}

export const MermaidBlock = memo(MermaidBlockInner);
