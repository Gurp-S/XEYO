import {useEffect, useRef, useState} from 'react';

type HSV = {h: number; s: number; v: number};

type Props = {
	/** 当前生效色（#rrggbb）；空 = 主题默认 */
	value: string;
	/** 主题默认色，用于展示与拖动初值 */
	fallback: string;
	onChange: (hex: string) => void;
};

function clamp01(n: number): number {
	return Math.min(1, Math.max(0, n));
}

export function hexToRgb(hex: string): [number, number, number] {
	const h = hex.replace('#', '');
	return [
		parseInt(h.slice(0, 2), 16) || 0,
		parseInt(h.slice(2, 4), 16) || 0,
		parseInt(h.slice(4, 6), 16) || 0,
	];
}

function rgbToHex(r: number, g: number, b: number): string {
	const to = (n: number) =>
		Math.round(Math.min(255, Math.max(0, n)))
			.toString(16)
			.padStart(2, '0');
	return `#${to(r)}${to(g)}${to(b)}`;
}

export function hexToHsv(hex: string): HSV {
	const [r, g, b] = hexToRgb(hex).map(n => n / 255) as [number, number, number];
	const max = Math.max(r, g, b);
	const min = Math.min(r, g, b);
	const d = max - min;
	let h = 0;
	if (d > 0) {
		if (max === r) {
			h = ((g - b) / d) % 6;
		} else if (max === g) {
			h = (b - r) / d + 2;
		} else {
			h = (r - g) / d + 4;
		}
		h = (h * 60 + 360) % 360;
	}
	return {h, s: max === 0 ? 0 : d / max, v: max};
}

function hsvToHex({h, s, v}: HSV): string {
	const c = v * s;
	const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
	const m = v - c;
	let rgb: [number, number, number];
	if (h < 60) {
		rgb = [c, x, 0];
	} else if (h < 120) {
		rgb = [x, c, 0];
	} else if (h < 180) {
		rgb = [0, c, x];
	} else if (h < 240) {
		rgb = [0, x, c];
	} else if (h < 300) {
		rgb = [x, 0, c];
	} else {
		rgb = [c, 0, x];
	}
	return rgbToHex((rgb[0] + m) * 255, (rgb[1] + m) * 255, (rgb[2] + m) * 255);
}

/**
 * 简约版强调色选择器：明度/饱和度面板 + 色相条 + HEX，仅此三件。
 * 圆润、低视觉噪音，跟随主题变量。
 */
export function AccentColorPicker({value, fallback, onChange}: Props) {
	const base = value || fallback;
	const [hsv, setHsv] = useState<HSV>(() => hexToHsv(base));
	const [hex, setHex] = useState(base);
	const squareRef = useRef<HTMLDivElement>(null);
	const hueRef = useRef<HTMLDivElement>(null);

	// 外部改动（推荐色 / 历史 / 恢复默认）→ 同步内部 HSV
	useEffect(() => {
		if (value !== hex) {
			const src = value || fallback;
			setHsv(hexToHsv(src));
			setHex(src);
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [value, fallback]);

	const commit = (next: HSV) => {
		setHsv(next);
		const out = hsvToHex(next);
		setHex(out);
		onChange(out);
	};

	const fromSquare = (e: React.PointerEvent) => {
		const el = squareRef.current;
		if (!el) {
			return;
		}
		const r = el.getBoundingClientRect();
		commit({
			...hsv,
			s: clamp01((e.clientX - r.left) / r.width) * 0.92,
			v: 1 - clamp01((e.clientY - r.top) / r.height) * 0.94 + 0.06,
		});
	};

	const fromHue = (e: React.PointerEvent) => {
		const el = hueRef.current;
		if (!el) {
			return;
		}
		const r = el.getBoundingClientRect();
		commit({
			...hsv,
			h: clamp01((e.clientX - r.left) / r.width) * 360,
		});
	};

	const drag = (fn: (e: React.PointerEvent) => void) => ({
		onPointerDown: (e: React.PointerEvent) => {
			e.currentTarget.setPointerCapture(e.pointerId);
			fn(e);
		},
		onPointerMove: (e: React.PointerEvent) => {
			if (e.buttons & 1) {
				fn(e);
			}
		},
	});

	const cur = hsvToHex(hsv);

	return (
		<div className="space-y-3 pt-0.5">
			{/* 明度 × 饱和度 */}
			<div
				ref={squareRef}
				{...drag(fromSquare)}
				role="slider"
				aria-label="饱和度与明度"
				className="relative h-24 w-full cursor-crosshair touch-none rounded-2xl border border-line/50"
				style={{
					background: `linear-gradient(to top, #000, transparent), linear-gradient(to right, #fff, hsl(${hsv.h} 70% 62%))`,
				}}
			>
				<span
					className="pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[0_1px_4px_rgb(0_0_0/0.3)]"
					style={{
						left: `${(hsv.s / 0.92) * 100}%`,
						top: `${(1 - (hsv.v - 0.06) / 0.94) * 100}%`,
						background: cur,
					}}
				/>
			</div>

			{/* 色相 */}
			<div
				ref={hueRef}
				{...drag(fromHue)}
				role="slider"
				aria-label="色相"
				aria-valuenow={Math.round(hsv.h)}
				className="relative h-2.5 w-full cursor-pointer touch-none rounded-full"
				style={{
					background:
						'linear-gradient(to right, #d9b8b1, #d9cfae, #b8cfba, #aecbd0, #b1b8d4, #cfb4cd, #d9b8b1)',
				}}
			>
				<span
					className="pointer-events-none absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[0_1px_4px_rgb(0_0_0/0.3)]"
					style={{left: `${(hsv.h / 360) * 100}%`, background: cur}}
				/>
			</div>
		</div>
	);
}
