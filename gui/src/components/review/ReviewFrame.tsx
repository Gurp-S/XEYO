import {useLayoutEffect, useRef} from 'react';

/** One continuous surface with a chrome tint; no independently clipped backgrounds. */
export function ReviewFrame() {
	const svgRef = useRef<SVGSVGElement>(null);
	const pathRef = useRef<SVGPathElement>(null);

	useLayoutEffect(() => {
		const svg = svgRef.current;
		const path = pathRef.current;
		const root = svg?.closest<HTMLElement>('.xy-app-surface');
		if (!svg || !path || !root) return;
		let host: HTMLElement | null = null;
		const paint = () => {
			const outer = root.getBoundingClientRect();
			let shape = `M0 0H${outer.width}V${outer.height}H0Z`;
			if (host) {
				const bounds = host.getBoundingClientRect();
				const x = bounds.left - outer.left;
				const y = bounds.top - outer.top;
				const right = bounds.right - outer.left;
				const bottom = bounds.bottom - outer.top;
				const radius = Math.min(
					parseFloat(getComputedStyle(host).borderTopLeftRadius) || 0,
					bounds.width / 2, bounds.height / 2,
				);
				shape += `M${x + radius} ${y}H${right - radius}A${radius} ${radius} 0 0 1 ${right} ${y + radius}V${bottom - radius}A${radius} ${radius} 0 0 1 ${right - radius} ${bottom}H${x + radius}A${radius} ${radius} 0 0 1 ${x} ${bottom - radius}V${y + radius}A${radius} ${radius} 0 0 1 ${x + radius} ${y}Z`;
			}
			if (path.getAttribute('d') !== shape) path.setAttribute('d', shape);
		};
		const resize = new ResizeObserver(paint);
		resize.observe(root);
		const bindHost = () => {
			const next = root.querySelector<HTMLElement>('.xy-pane-chat-host');
			if (next !== host) {
				if (host) resize.unobserve(host);
				host = next;
				if (host) resize.observe(host);
				paint();
			}
		};
		// Routes can replace the chat host without remounting the outer shell.
		const mutation = new MutationObserver(() => {
			// Streaming prose changes descendants, not the host itself.
			if (!host || !root.contains(host)) bindHost();
		});
		mutation.observe(root, {childList: true, subtree: true});
		bindHost();
		paint();
		window.addEventListener('resize', paint);
		return () => {
			resize.disconnect();
			mutation.disconnect();
			window.removeEventListener('resize', paint);
		};
	}, []);

	return (
		<svg ref={svgRef} aria-hidden className="xy-review-frame">
			<rect width="100%" height="100%" fill="var(--xy-review-surface)" />
			<path ref={pathRef} fill="var(--xy-review-frame-tint)" fillRule="evenodd" stroke="none" />
		</svg>
	);
}
