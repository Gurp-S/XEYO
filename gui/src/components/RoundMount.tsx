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
	/** 为 false 时跳过 ResizeObserver 高度缓存（如正在流式输出的轮次）。 */
	cacheHeight?: boolean;
	children: ReactNode;
};

/**
 * 通过 IntersectionObserver 延迟挂载视口外的轮次。
 * 缓存实测高度，使占位块与上次已知尺寸一致（避免 120px 跳动）。
 *
 * 此处禁用 content-visibility：它会与 position:sticky + clip-path 的
 * 打孔逻辑冲突，导致 transcript 增长时吸顶内容闪烁。
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
