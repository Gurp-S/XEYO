import {
	cancelFrameTask,
	createFrameKey,
	scheduleFrameRead,
} from '@/lib/frameScheduler';
import {
	getRoundHeightOrDefault,
	setRoundHeight,
} from '@/lib/roundHeights';
import {
	type ReactNode,
	useEffect,
	useRef,
	useState,
} from 'react';

type RoundMountProps = {
	roundId: string;
	always: boolean;
	root: HTMLElement | null;
	/** When false, skip ResizeObserver height caching (e.g. live streaming round). */
	cacheHeight?: boolean;
	children: ReactNode;
};

/**
 * Defers mounting off-screen rounds via IntersectionObserver.
 * Caches measured height so placeholders match last known size (no 120px jump).
 *
 * Do NOT use content-visibility here: it fights position:sticky + clip-path
 * punch holes and causes sticky flicker while the transcript grows.
 */
export function RoundMount({
	roundId,
	always,
	root,
	cacheHeight = true,
	children,
}: RoundMountProps) {
	const hostRef = useRef<HTMLElement | null>(null);
	const [mounted, setMounted] = useState(always);
	const measureKeyRef = useRef(createFrameKey(`round-h-${roundId}`));

	useEffect(() => {
		if (always) {
			setMounted(true);
			return;
		}
		if (mounted) {
			return;
		}
		const el = hostRef.current;
		if (!el || typeof IntersectionObserver === 'undefined') {
			setMounted(true);
			return;
		}
		const io = new IntersectionObserver(
			entries => {
				if (entries.some(e => e.isIntersecting)) {
					setMounted(true);
				}
			},
			{root: root ?? undefined, rootMargin: '240px 0px'},
		);
		io.observe(el);
		return () => io.disconnect();
	}, [always, mounted, root]);

	const renderMounted = mounted || always;
	const cachedH = getRoundHeightOrDefault(roundId);

	useEffect(() => {
		if (!renderMounted || !cacheHeight) {
			return;
		}
		const el = hostRef.current;
		if (!el || typeof ResizeObserver === 'undefined') {
			return;
		}
		const key = measureKeyRef.current;
		const ro = new ResizeObserver(() => {
			scheduleFrameRead(key, () => {
				const h = el.getBoundingClientRect().height;
				setRoundHeight(roundId, h);
			});
		});
		ro.observe(el);
		return () => {
			ro.disconnect();
			cancelFrameTask(key);
		};
	}, [renderMounted, roundId, cacheHeight]);

	return (
		<section
			ref={hostRef}
			data-round-id={roundId}
			className="relative xy-round-mount"
			style={renderMounted ? undefined : {minHeight: cachedH}}
		>
			{renderMounted ? (
				children
			) : (
				<div
					aria-hidden
					style={{minHeight: cachedH}}
					className="pointer-events-none"
				/>
			)}
		</section>
	);
}
