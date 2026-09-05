/**
 * uiScanStyles.ts — 程序化 GUI 样式异常扫描谓词（全量审计 · 几何之外的补充维度）。
 *
 * 与 uiScan.ts 同一约束：`scanStyles` 完全自包含，经 `page.evaluate` 序列化进
 * 浏览器上下文执行，函数体内不得引用任何文件级外部引用。
 *
 * 判定谓词：
 * - TINY_FONT     可读性：有直接文本的元素 font-size < 9px（肉眼难读，多为 bug）
 * - LOW_CONTRAST  文字与有效合成背景对比度 < 3.0（AA 需 4.5；玻璃/半透明 UI 有噪声，
 *                 结果归「核验」级，需人工分辨是否有意为之）
 * - INVISIBLE_TEXT 有直接文本但有效不透明度 ≈ 0（多为动画残留/忘记清理的透明态）
 */

export type StyleViolationKind = 'TINY_FONT' | 'LOW_CONTRAST' | 'INVISIBLE_TEXT';

export type StyleViolation = {
	kind: StyleViolationKind;
	selector: string;
	detail: string;
	preview?: string;
};

export type StyleScanResult = {
	scanned: number;
	violations: StyleViolation[];
	byKind: Record<StyleViolationKind, number>;
};

export type StyleScanOptions = {
	tinyFontPx?: number;
	contrastMin?: number;
	invisibleAlpha?: number;
};

export function scanStyles(opts: StyleScanOptions = {}): StyleScanResult {
	const {
		tinyFontPx = 9,
		contrastMin = 3.0,
		invisibleAlpha = 0.15,
	} = opts;

	const vw = window.innerWidth;
	const vh = window.innerHeight;
	const VP_PAD = 8;

	// —— 内联 helper ——
	function parseColor(s: string): [number, number, number, number] | null {
		const m = s.match(/rgba?\(([^)]+)\)/);
		if (!m) return null;
		const parts = m[1]!.split(',').map(p => parseFloat(p.trim()));
		if (parts.length < 3 || parts.some(n => Number.isNaN(n))) return null;
		return [parts[0]!, parts[1]!, parts[2]!, parts.length >= 4 ? parts[3]! : 1];
	}

	function srgbToLinear(c: number): number {
		const x = c / 255;
		return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
	}

	function luminance(rgb: [number, number, number]): number {
		return (
			0.2126 * srgbToLinear(rgb[0]) +
			0.7152 * srgbToLinear(rgb[1]) +
			0.0722 * srgbToLinear(rgb[2])
		);
	}

	function contrastRatio(a: [number, number, number], b: [number, number, number]): number {
		const la = luminance(a);
		const lb = luminance(b);
		const hi = Math.max(la, lb);
		const lo = Math.min(la, lb);
		return (hi + 0.05) / (lo + 0.05);
	}

	/** 从 documentElement 往下逐层 alpha 合成出有效背景 RGB（半透明玻璃逐层叠加）。 */
	function effectiveBg(el: Element): [number, number, number] | null {
		const chain: [number, number, number, number][] = [];
		let node: Element | null = el;
		while (node) {
			const st = getComputedStyle(node);
			const bg = parseColor(st.backgroundColor);
			if (bg && bg[3] > 0) {
				chain.push(bg);
			}
			node = node.parentElement;
		}
		// 链条是 el→root，反转后从最外层开始合成；底色取纸面近似：先假定白，
		// 但若 html/body 本身有背景会先覆盖它，故足够。
		let out: [number, number, number] = [255, 255, 255];
		for (let i = chain.length - 1; i >= 0; i -= 1) {
			const [r, g, b, a] = chain[i]!;
			out = [
				Math.round(r * a + out[0] * (1 - a)),
				Math.round(g * a + out[1] * (1 - a)),
				Math.round(b * a + out[2] * (1 - a)),
			];
		}
		return out;
	}

	function buildSelector(el: Element): string {
		const parts: string[] = [];
		let node: Element | null = el;
		while (node && node !== document.documentElement && parts.length < 6) {
			let part = node.tagName.toLowerCase();
			if (node.id) {
				parts.unshift(`${part}#${node.id}`);
				break;
			}
			const testId = node.getAttribute('data-testid');
			if (testId) {
				parts.unshift(`${part}[data-testid="${testId}"]`);
				break;
			}
			const parent: Element | null = node.parentElement;
			if (parent) {
				const same = Array.from(parent.children).filter(c => c.tagName === node!.tagName);
				if (same.length > 1) {
					const idx = (same as Element[]).indexOf(node) + 1;
					part += `:nth-of-type(${idx})`;
				}
			}
			parts.unshift(part);
			node = parent;
		}
		return parts.join(' > ');
	}

	function ownText(el: Element): string {
		let t = '';
		for (const n of el.childNodes) {
			if (n.nodeType === Node.TEXT_NODE) {
				t += n.textContent ?? '';
			}
		}
		return t.replace(/\s+/g, ' ').trim();
	}

	// —— 主遍历 ——
	const violations: StyleViolation[] = [];
	const all = Array.from(document.querySelectorAll<HTMLElement>('*'));
	let scanned = 0;
	for (const el of all) {
		const st = getComputedStyle(el);
		if (st.display === 'none' || st.visibility === 'hidden') continue;
		const tag = el.tagName.toLowerCase();
		if (tag === 'svg' || tag === 'path' || tag === 'rect' || tag === 'circle' ||
			tag === 'use' || tag === 'g') continue;
		const r = el.getBoundingClientRect();
		if (r.right < -VP_PAD || r.bottom < -VP_PAD || r.left > vw + VP_PAD || r.top > vh + VP_PAD) continue;
		const text = ownText(el);
		if (text.length < 2) continue;
		scanned += 1;

		// 元素整体不透明度：动画中途可能 < 1，仅极低时判 INVISIBLE_TEXT。
		const effAlpha = parseFloat(st.opacity || '1') *
			(parseColor(st.color)?.[3] ?? 1);
		if (effAlpha < invisibleAlpha) {
			violations.push({
				kind: 'INVISIBLE_TEXT',
				selector: buildSelector(el),
				detail: `有效不透明度 ${effAlpha.toFixed(3)} < ${invisibleAlpha}，文本「${text.slice(0, 20)}」肉眼不可见`,
				preview: text.slice(0, 60),
			});
			continue;
		}

		const fontSize = parseFloat(st.fontSize || '16');
		if (fontSize < tinyFontPx) {
			violations.push({
				kind: 'TINY_FONT',
				selector: buildSelector(el),
				detail: `font-size ${fontSize.toFixed(1)}px < ${tinyFontPx}px（文本「${text.slice(0, 20)}」）`,
				preview: text.slice(0, 60),
			});
		}

		const color = parseColor(st.color);
		if (color) {
			// 文字 alpha 合成到背景上再算对比度。
			const textAlpha = color[3];
			const bg = effectiveBg(el);
			if (bg) {
				const composited: [number, number, number] = [
					Math.round(color[0] * textAlpha + bg[0] * (1 - textAlpha)),
					Math.round(color[1] * textAlpha + bg[1] * (1 - textAlpha)),
					Math.round(color[2] * textAlpha + bg[2] * (1 - textAlpha)),
				];
				const ratio = contrastRatio(composited, bg);
				if (ratio < contrastMin) {
					violations.push({
						kind: 'LOW_CONTRAST',
						selector: buildSelector(el),
						detail: `对比度 ${ratio.toFixed(2)}:1 < ${contrastMin}:1（text rgba(${color.join(',')})，文本「${text.slice(0, 20)}」）`,
						preview: text.slice(0, 60),
					});
				}
			}
		}
	}

	const byKind: Record<StyleViolationKind, number> = {
		TINY_FONT: 0,
		LOW_CONTRAST: 0,
		INVISIBLE_TEXT: 0,
	};
	for (const v of violations) byKind[v.kind] += 1;
	return {scanned, violations, byKind};
}
