/**
 * uiScan.ts — 程序化 GUI 几何错位扫描谓词（解法一）。
 *
 * 目标：不靠人眼，把「可量化的几何违背」逐元素扫出来，输出带选择器、
 * 几何数字与 viewport 坐标的违规清单，供人工确认。无任何生产代码依赖。
 *
 * 核心约束：`scanLayout` 是**完全自包含**函数 —— 所有 helper 内联在函数体内，
 * 因为它是通过 `page.evaluate(scanLayout, opts)` 序列化进浏览器上下文执行的，
 * 函数外部的任何模块级引用都会在序列化后丢失。因此这里只能有一个顶层导出。
 *
 * 判定谓词（每项独立、可单独开关，便于按噪音调参）：
 * - H_OVERFLOW  横向溢出：元素右缘超出视口 / 内容宽超出容器可显示宽
 * - V_CLIP      纵向裁切：元素底缘超出其滚动容器可见底
 * - TEXT_CLIP   文本截断：scrollW/H 超 clientW/H 且 overflow 非 visible
 * - ZERO_SIZE   零尺寸渲染：元素有内容但宽或高 ≈ 0
 * - OVERLAP     元素重叠：两个非祖先关系的可见元素矩形相交面积超阈值
 *
 * 已知边界（不做、避免误报）：
 * - 审美类（间距不匀/字重/配色/图标像素偏移）不属于几何谓词，交截图人工面。
 * - 不判定「应一行却没一行/应居中却偏左」这类语义错位 —— 需逐组件预期值，
 *   属第二步按组件契约断言，本模块保持通用。
 */

export type ViolationKind =
	| 'H_OVERFLOW'
	| 'V_CLIP'
	| 'TEXT_CLIP'
	| 'ZERO_SIZE'
	| 'OVERLAP';

export type Geometry = {
	x: number;
	y: number;
	width: number;
	height: number;
};

export type Violation = {
	kind: ViolationKind;
	selector: string;
	geometry: Geometry;
	detail: number;
	hint: string;
	preview?: string;
	stableAnchor?: string;
};

export type ScanResult = {
	viewport: Geometry;
	violations: Violation[];
	scanned: number;
};

export type ScanPredicates = {
	H_OVERFLOW?: boolean;
	V_CLIP?: boolean;
	TEXT_CLIP?: boolean;
	ZERO_SIZE?: boolean;
	OVERLAP?: boolean;
};

export type ScanOptions = {
	predicates?: ScanPredicates;
	overlapRatio?: number;
	minTextLen?: number;
	/**
	 * 只扫描当前视口内的元素。默认 true：长转录/分栏会产生大量屏外内容，
	 * 若整页都扫会把这些「未显示到但本应可滚动」的长列表项误判为裁切/重叠。
	 * 打开时用滚动分屏多次扫以覆盖全量（见 spec）。
	 */
	viewportOnly?: boolean;
};

export type ScanResultSummary = ScanResult & {
	byKind: Record<ViolationKind, number>;
};

/**
 * 主扫描入口：完全自包含，交给 `page.evaluate(scanLayout, opts)` 在浏览器里跑。
 *
 * 注意：Playwright 会把本函数源码序列化进浏览器上下文，因此本函数体内不得
 * 引用任何文件内其他顶层函数/常量 —— 所有依赖都已内联。类型注解会被剥离，
 * 运行期只剩实现本身。
 */
export function scanLayout(opts: ScanOptions = {}): ScanResultSummary {
	const {
		predicates = {
			H_OVERFLOW: true,
			V_CLIP: true,
			TEXT_CLIP: true,
			ZERO_SIZE: true,
			OVERLAP: true,
		},
		overlapRatio = 0.12,
		minTextLen = 8,
		viewportOnly = true,
	} = opts;

	const FLOAT_EPS = 1.5; // px，抗亚像素/缩放噪声
	const vw = window.innerWidth;
	const vh = window.innerHeight;
	// 视口外扩一点点，允许紧贴边缘的贴边元素参与（抗 DPR 取整噪声）。
	const VP_PAD = 8;

	// —— 内联 helper ——
	function isVisible(el: Element): boolean {
		const style = getComputedStyle(el);
		if (style.display === 'none' || style.visibility === 'hidden') {
			return false;
		}
		return true;
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
				const same = Array.from(parent.children).filter(
					(c) => c.tagName === node!.tagName,
				);
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

	function stableAnchor(el: Element): string | undefined {
		return el.getAttribute('data-testid') || el.id || undefined;
	}

	function previewOf(el: Element): string | undefined {
		const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
		return text ? text.slice(0, 60) : undefined;
	}

	function scrollContainerFor(
		el: Element,
	): {el: HTMLElement; clientWidth: number; clientHeight: number} | null {
		let parent: Element | null = el.parentElement;
		while (parent) {
			const st = getComputedStyle(parent);
			const canScrollX = st.overflowX !== 'visible' && st.overflowX !== 'clip';
			const canScrollY = st.overflowY !== 'visible' && st.overflowY !== 'clip';
			if (canScrollX || canScrollY) {
				const p = parent as HTMLElement;
				return {el: p, clientWidth: p.clientWidth, clientHeight: p.clientHeight};
			}
			parent = parent.parentElement;
		}
		return null;
	}

	/** SVG 内部图元是图形内容不是布局元素，跳过以免把图标当错位/重叠。 */
	function isSvgInner(el: Element): boolean {
		const tag = el.tagName.toLowerCase();
		if (tag === 'svg') {
			return true;
		}
		return tag === 'path' || tag === 'rect' || tag === 'circle' ||
			tag === 'line' || tag === 'polyline' || tag === 'polygon' ||
			tag === 'ellipse' || tag === 'use' || tag === 'g' || tag === 'text' || tag === 'tspan';
	}

	// —— 主遍历 ——
	const violations: Violation[] = [];
	const all = Array.from(document.querySelectorAll<HTMLElement>('*'));
	const visible: HTMLElement[] = [];
	for (const el of all) {
		if (!isVisible(el) || isSvgInner(el)) {
			continue;
		}
		if (viewportOnly) {
			const r = el.getBoundingClientRect();
			// 只保留与视口（±padding）相交的元素，剔除屏外长列表项。
			if (
				r.right < -VP_PAD ||
				r.bottom < -VP_PAD ||
				r.left > vw + VP_PAD ||
				r.top > vh + VP_PAD
			) {
				continue;
			}
		}
		visible.push(el);
	}

	type Raw = Omit<Violation, 'selector' | 'geometry'> & {
		geometry: DOMRect;
		anchor: Element;
	};
	const push = (v: Raw) => {
		violations.push({
			kind: v.kind,
			selector: buildSelector(v.anchor),
			geometry: {
				x: Math.round(v.geometry.x),
				y: Math.round(v.geometry.y),
				width: Math.round(v.geometry.width),
				height: Math.round(v.geometry.height),
			},
			detail: v.detail,
			hint: v.hint,
			preview: v.preview,
			stableAnchor: v.stableAnchor,
		});
	};

	// 一次读全部 rect（避免逐元素读取引起布局抖动叠加误报）。
	const rects = new Map<Element, DOMRect>();
	for (const el of visible) {
		rects.set(el, el.getBoundingClientRect());
	}

	for (const el of visible) {
		const rect = rects.get(el)!;
		const style = getComputedStyle(el);
		const text = (el.textContent || '').replace(/\s+/g, ' ').trim();
		const hasContent = text.length >= minTextLen || el.childElementCount > 0;

		if (predicates.H_OVERFLOW) {
			const sc = scrollContainerFor(el);
			if (sc) {
				if (rect.right > vw + FLOAT_EPS) {
					push({
						kind: 'H_OVERFLOW',
						geometry: rect,
						detail: Math.round(rect.right - vw),
						hint: `元素右缘 ${Math.round(rect.right)} 超出视口宽 ${vw}`,
						preview: previewOf(el),
						stableAnchor: stableAnchor(el),
						anchor: el,
					});
				}
				if (sc.clientWidth > 0 && el.scrollWidth > sc.clientWidth + FLOAT_EPS) {
					push({
						kind: 'H_OVERFLOW',
						geometry: rect,
						detail: Math.round(el.scrollWidth - sc.clientWidth),
						hint: `内容宽 ${Math.round(el.scrollWidth)} 超出容器可显示宽 ${sc.clientWidth}`,
						preview: previewOf(el),
						stableAnchor: stableAnchor(el),
						anchor: el,
					});
				}
			}
		}

		if (predicates.V_CLIP) {
			const sc = scrollContainerFor(el);
			if (sc) {
				const parentRect = sc.el.getBoundingClientRect();
				if (rect.bottom > parentRect.bottom + FLOAT_EPS) {
					push({
						kind: 'V_CLIP',
						geometry: rect,
						detail: Math.round(rect.bottom - parentRect.bottom),
						hint: `元素底缘 ${Math.round(rect.bottom)} 超出容器底 ${Math.round(parentRect.bottom)}，疑似被裁切`,
						preview: previewOf(el),
						stableAnchor: stableAnchor(el),
						anchor: el,
					});
				}
			}
		}

		if (predicates.TEXT_CLIP && el instanceof HTMLElement) {
			const hiddenX = style.overflowX !== 'visible' && style.overflowX !== 'clip';
			const hiddenY = style.overflowY !== 'visible' && style.overflowY !== 'clip';
			if (hiddenX || hiddenY) {
				if (
					el.scrollWidth > el.clientWidth + FLOAT_EPS ||
					el.scrollHeight > el.clientHeight + FLOAT_EPS
				) {
					push({
						kind: 'TEXT_CLIP',
						geometry: rect,
						detail:
							Math.round(el.scrollWidth - el.clientWidth) ||
							Math.round(el.scrollHeight - el.clientHeight),
						hint: `scrollW/H ${el.scrollWidth}/${el.scrollHeight} 超 client ${el.clientWidth}/${el.clientHeight}，溢出方向被隐藏`,
						preview: previewOf(el),
						stableAnchor: stableAnchor(el),
						anchor: el,
					});
				}
			}
		}

		if (
			predicates.ZERO_SIZE &&
			hasContent &&
			el instanceof HTMLElement &&
			(rect.width <= 0.5 || rect.height <= 0.5) &&
			(text.length > 0 || el.childElementCount > 0)
		) {
			push({
				kind: 'ZERO_SIZE',
				geometry: rect,
				detail: Math.round(Math.max(rect.width, rect.height)),
				hint: `有内容但渲染尺寸 ${Math.round(rect.width)}×${Math.round(rect.height)}，疑似零尺寸/塌陷`,
				preview: previewOf(el),
				stableAnchor: stableAnchor(el),
				anchor: el,
			});
		}
	}

	// OVERLAP —— O(n²) 比较；限定可见且非零尺寸元素，并设规模上限防卡死。
	if (predicates.OVERLAP) {
		const sized = visible.filter((el) => {
			const r = rects.get(el)!;
			return r.width > 0 && r.height > 0;
		});
		// 结构壳（视口级容器/背景层）覆盖整个区域属正常，不当作重叠对成员。
		const isShell = (r: DOMRect) =>
			r.width >= vw * 0.85 && r.height >= vh * 0.85;
		const candidates = sized.filter((el) => {
			return !isShell(rects.get(el)!);
		}).slice(0, 2500);
		// 重叠按元素去重：一个悬浮层/容器会与无数下级元素相交，
		// 若每个配对都报，同一条「X 盖住了整片」会刷屏。每个元素至多报一次，
		// 取与其相交占比最大的对手元素。
		const reportedA = new Set<Element>();
		for (let i = 0; i < candidates.length; i += 1) {
			const a = candidates[i]!;
			if (reportedA.has(a)) {
				continue;
			}
			const ra = rects.get(a)!;
			let best: {b: Element; inter: number} | null = null;
			for (let j = 0; j < candidates.length; j += 1) {
				if (j === i) {
					continue;
				}
				const b = candidates[j]!;
				if (a.contains(b) || b.contains(a)) {
					continue;
				}
				const rb = rects.get(b)!;
				const ix = Math.max(0, Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left));
				const iy = Math.max(0, Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top));
				const inter = ix * iy;
				if (inter <= 0) {
					continue;
				}
				const ratioA = inter / (ra.width * ra.height);
				const ratioB = inter / (rb.width * rb.height);
				if (
					Math.max(ratioA, ratioB) >= overlapRatio &&
					Math.min(ratioA, ratioB) >= overlapRatio * 0.4
				) {
					if (!best || inter > best.inter) {
						best = {b, inter};
					}
				}
			}
			if (best) {
				const rb = rects.get(best.b)!;
				const ratio = best.inter / Math.min(ra.width * ra.height, rb.width * rb.height);
				push({
					kind: 'OVERLAP',
					geometry: ra,
					detail: Math.round(ratio * 100),
					hint: `A(${previewOf(a) ?? a.tagName}) 与 B(${previewOf(best.b) ?? best.b.tagName}) 相交 ${Math.round(ratio * 100)}%`,
					preview: previewOf(a),
					stableAnchor: stableAnchor(a),
					anchor: a,
				});
				reportedA.add(a);
				reportedA.add(best.b);
			}
		}
	}

	const byKind: Record<ViolationKind, number> = {
		H_OVERFLOW: 0,
		V_CLIP: 0,
		TEXT_CLIP: 0,
		ZERO_SIZE: 0,
		OVERLAP: 0,
	};
	for (const v of violations) {
		byKind[v.kind] += 1;
	}

	return {
		viewport: {x: 0, y: 0, width: vw, height: vh},
		violations,
		scanned: visible.length,
		byKind,
	};
}
