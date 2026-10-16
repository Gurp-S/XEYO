type Anchor = {top: number; right: number; bottom: number};
export type AnchoredMenuGeometry = {
	right: number;
	top?: number;
	bottom?: number;
	placement: 'above' | 'below';
	maxHeight: number;
};

/** Keep anchored menus inside the viewport, including anchors near the left edge. */
export function anchoredMenuGeometry(
	anchor: Anchor,
	viewport: {width: number; height: number},
	preferredWidth: number,
): AnchoredMenuGeometry {
	const edge = 8;
	const gap = 8;
	const width = Math.min(preferredWidth, Math.max(1, viewport.width - edge * 2));
	const left = Math.max(edge, Math.min(anchor.right - width, viewport.width - edge - width));
	const above = Math.max(0, anchor.top - gap - edge);
	const below = Math.max(0, viewport.height - anchor.bottom - gap - edge);
	const placement = below > above ? 'below' : 'above';
	return {
		right: Math.max(edge, viewport.width - left - width),
		placement,
		maxHeight: Math.max(1, Math.floor(placement === 'below' ? below : above)),
		...(placement === 'below'
			? {top: Math.max(edge, anchor.bottom + gap)}
			: {bottom: Math.max(edge, viewport.height - anchor.top + gap)}),
	};
}
