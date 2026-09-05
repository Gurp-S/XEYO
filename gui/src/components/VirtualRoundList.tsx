import {
	type MutableRefObject,
	type ReactNode,
	type RefObject,
	useCallback,
	useEffect,
	useLayoutEffect,
	useRef,
	useState,
} from 'react';
import {
	cancelFrameTask,
	createFrameKey,
	scheduleFrameRead,
} from '@/lib/frameScheduler';
import {getRoundHeightsVersion, subscribeRoundHeights} from '@/lib/roundHeights';
import {
	anchorScrollTop,
	captureViewportAnchor,
	computeRoundPrefix,
	mergeIntervals,
	roundIndexAtOffset,
	roundWindowFor,
	type RoundWindow,
} from '@/lib/roundVirtual';
import {ALWAYS_MOUNT_LATEST} from '@/lib/roundWindow';

export type VirtualRoundRenderContext = {
	/** 本轮由虚拟窗口挂载；跳过 RoundMount 的 IO 延迟。 */
	bypassRoundMountIo: boolean;
};

/**
 * 轮数 ≤ 此阈值时全挂载(不做窗口化)，让浏览器按真实 DOM 高度给出正确 scrollHeight。
 * 窗口化的"估算取窗 + 量测回写"反馈链曾是滚动抖动/墙的根源——高度表缓存
 * (roundHeights + ensurePrefix 的 heightsVersion 失效)落地后窗口化已稳，
 * 阈值从 150 降到 40：全挂载的切换延迟 ≈ O(全会话 markdown)，40 轮以上
 * 会话切换卡顿显著(2026-09-05 排查报告 S1)；只有极小会话保留零估算全挂载。
 */
export const VIRTUAL_WINDOW_THRESHOLD_ROUNDS = 40;

/** 前缀和查询句柄：viewport 的 rail 高亮 / 跳轮用（无需接触 DOM）。 */
export type VirtualRoundListApi = {
	/** content 坐标（0 = 首轮顶部）→ 轮次下标（越过末尾返回 count）。 */
	indexAt: (offset: number) => number;
	/** 轮次下标 → content 坐标顶部偏移。 */
	offsetOf: (index: number) => number;
	/** 全部轮次的估计总高（spacer 布局下的 content 内容高）。 */
	totalHeight: () => number;
};

export type VirtualRoundListProps = {
	roundIds: readonly string[];
	scrollElement: HTMLElement | null;
	contentRef: RefObject<HTMLElement | null>;
	smoothness: boolean;
	sessionSwitching: boolean;
	forcedIndices: ReadonlySet<number>;
	ioAvailable: boolean;
	/**
	 * 会话落地 / 冷装载首帧时是否贴底。贴底落位由本列表在自己的
	 * useLayoutEffect（先于父级）里完成，保证首个可见帧就是落位后的窗口。
	 */
	stickToBottomRef: RefObject<boolean>;
	/** rail / jump 用的前缀和句柄。 */
	apiRef: MutableRefObject<VirtualRoundListApi | null>;
	/**
	 * sticky 吸顶气泡交换期间由外部置色（~80ms）。此窗口内暂停滚动补偿，
	 * 让吸顶交换先稳定下来，避免"交换中途改变高度 → 补偿写 scrollTop → 和
	 * 交换互相争抢"的抖动。只暂停补偿，窗口实测照常。
	 */
	measureMuteRef?: RefObject<boolean | null>;
	renderRound: (index: number, ctx: VirtualRoundRenderContext) => ReactNode;
};

/**
 * Round list host — 自研窗口化。
 *
 * 只渲染「视口 ± overscan ∪ 最新 ALWAYS_MOUNT_LATEST 轮 ∪ 强制轮」，
 * 其余轮次用 spacer（Σ roundHeights 缓存高度）占位；挂载轮次经
 * RoundMount 的 ResizeObserver 实测回写高度表，前缀和随之收敛。
 *
 * TanStack Virtual 保持撤除：其 ResizeObserver → resizeItem 反馈环与
 * sticky / TurnRail 文档流打架（React max update depth）。这里高度更新
 * 只写 Map（不落 React state），窗口边界不变就零渲染。
 *
 * measure / ensurePrefix 一律经 stateRef 读最新 props —— 订阅类 effect
 * （scroll / heights）只在 allMount 变化时重建，闭包不得捕获旧 roundIds。
 */
export function VirtualRoundList({
	roundIds,
	scrollElement,
	contentRef,
	smoothness,
	sessionSwitching,
	forcedIndices,
	ioAvailable,
	stickToBottomRef,
	apiRef,
	measureMuteRef,
	renderRound,
}: VirtualRoundListProps) {
	const count = roundIds.length;
	// 轮数在阈值内 → 全挂载(浏览器直接按真实 DOM 高度得到有效 scrollHeight),
	// 零估算、零"量测→重建→取窗"反馈,从根本上消除滚动抖动/墙/与 sticky 争抢。
	// 超过阈值才走窗口化。注意:窗口化不再被 smoothness 关闭劫持——关平滑是为
	// 省 CSS 动画开销,不应反而让大会话切换全量挂载(排查报告 S2);
	// 挂载集合由窗口段决定,段内轮次经 bypassRoundMountIo 强制挂载。
	const allMount = !ioAvailable || count <= VIRTUAL_WINDOW_THRESHOLD_ROUNDS;
	const [win, setWin] = useState<RoundWindow>({start: 0, end: 0});
	const prefixRef = useRef<number[]>([0]);
	const prefixIdsRef = useRef<readonly string[] | null>(null);
	/** 高度表版本：实测回写使前缀和失效时据此重建，消除估计-真实高度错位。 */
	const heightsVersionRef = useRef(getRoundHeightsVersion());
	const didLandRef = useRef(false);
	const measureKeyRef = useRef(createFrameKey('round-window'));
	void contentRef;
	// smoothness 不再参与 allMount 判据(S2);保留 prop 兼容调用方签名。
	void smoothness;

	// 最新 props 镜像：订阅回调 / api 都从这里读，避免陈旧闭包。
	const stateRef = useRef({roundIds, scrollElement, allMount});
	stateRef.current = {roundIds, scrollElement, allMount};

	const ensurePrefix = useCallback((): number[] => {
		const ids = stateRef.current.roundIds;
		const hVersion = getRoundHeightsVersion();
		// 前缀和失效条件：轮次集合变化 **或** 高度表被实测回写。
		// 此前只在 roundIds 变化时重建 —— 高度回写永远不落进前缀和，
		// 窗口/spacer 一直沿用默认 120 的旧坐标，即「估计-真实高度错位」本体。
		const idsChanged = prefixIdsRef.current !== ids;
		const heightsChanged = heightsVersionRef.current !== hVersion;
		if (!idsChanged && !heightsChanged) {
			return prefixRef.current;
		}
		prefixIdsRef.current = ids;
		heightsVersionRef.current = hVersion;
		prefixRef.current = computeRoundPrefix(ids);
		return prefixRef.current;
	}, []);

	const measure = useCallback((landBottom: boolean) => {
		const {scrollElement: el, allMount: all} = stateRef.current;
		if (all || !el) {
			return;
		}
		if (landBottom) {
			// 读 scrollHeight 强制布局后写 scrollTop —— 都在绘制前完成。
			el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight);
		}
		// 必须在 ensurePrefix（可能重建前缀和）**之前**捕获锚点，才能拿到旧坐标。
		const before = prefixRef.current;
		const anchor = captureViewportAnchor(before, el.scrollTop);
		const prefix = ensurePrefix();
		const rebuilt = prefix !== before;
		// 高度实测回写使前缀和整体平移时,把 scrollTop 重对齐回同一内容点,
		// 否则"上方轮次长高"会把视口内容顶走(往上滚回看历史时的闪跳)。
		// 只在坐标空间真的平移、锚点有效、目标落在有效可滚范围内时才写,
		// 避免越界补偿把滚到底部的用户拽飞或触发 clamp 循环。
		const muted = Boolean(measureMuteRef?.current);
		if (!landBottom && rebuilt && anchor && !muted) {
			const target = anchorScrollTop(prefix, anchor);
			const maxScroll = Math.max(0, el.scrollHeight - el.clientHeight);
			if (target >= 0 && target <= maxScroll && Math.abs(target - el.scrollTop) > 0.5) {
				el.scrollTop = target;
			}
		}
		const next = roundWindowFor(
			prefix,
			el.scrollTop,
			el.clientHeight,
		);
		setWin(prev =>
			prev.start === next.start && prev.end === next.end ? prev : next,
		);
	}, [ensurePrefix]);

	const scheduleMeasure = useCallback(() => {
		scheduleFrameRead(measureKeyRef.current, () => measure(false));
	}, [measure]);

	// 会话切换 / 冷装载首帧：同步取窗（贴底时先落位），保证首帧正确。
	useLayoutEffect(() => {
		if (allMount) {
			return;
		}
		const land = !didLandRef.current || sessionSwitching;
		didLandRef.current = true;
		if (land && !stickToBottomRef.current) {
			// 不跟尾：浏览器已把 scrollTop clamp 到新内容，按当前位置取窗。
			measure(false);
		} else {
			measure(land);
		}
	}, [roundIds, sessionSwitching, scrollElement, allMount, measure, stickToBottomRef]);

	// 滚动 → 帧合并取窗。
	useEffect(() => {
		if (allMount || !scrollElement) {
			return;
		}
		const onScroll = () => scheduleMeasure();
		scrollElement.addEventListener('scroll', onScroll, {passive: true});
		return () => {
			scrollElement.removeEventListener('scroll', onScroll);
			cancelFrameTask(measureKeyRef.current);
		};
	}, [allMount, scrollElement, scheduleMeasure]);

	// 高度实测回写 → 前缀和失效 → 帧合并重取窗（窗口不变则零渲染）。
	useEffect(() => {
		if (allMount) {
			return;
		}
		return subscribeRoundHeights(() => scheduleMeasure());
	}, [allMount, scheduleMeasure]);

	// 前缀和查询句柄（viewport / rail 用）。
	useLayoutEffect(() => {
		const api: VirtualRoundListApi = {
			indexAt: (offset: number) =>
				roundIndexAtOffset(ensurePrefix(), offset),
			offsetOf: (index: number) => {
				const prefix = ensurePrefix();
				const clamped = Math.max(0, Math.min(index, stateRef.current.roundIds.length));
				return prefix[clamped] ?? 0;
			},
			totalHeight: () => {
				const prefix = ensurePrefix();
				return prefix[prefix.length - 1] ?? 0;
			},
		};
		apiRef.current = api;
		return () => {
			apiRef.current = null;
		};
	}, [apiRef, ensurePrefix]);

	// 挂载集合 = 视口窗口 ∪ 最新 N 轮 ∪ 强制轮（合并为不相交段）。
	const segments: RoundWindow[] = (() => {
		if (allMount || count === 0) {
			return count > 0 ? [{start: 0, end: count}] : [];
		}
		const list: RoundWindow[] = [win];
		list.push({
			start: Math.max(0, count - ALWAYS_MOUNT_LATEST),
			end: count,
		});
		for (const idx of forcedIndices) {
			if (idx >= 0 && idx < count) {
				list.push({start: idx, end: idx + 1});
			}
		}
		return mergeIntervals(list);
	})();

	const prefix = ensurePrefix();
	const nodes: ReactNode[] = [];
	let cursor = 0;
	for (const seg of segments) {
		if (seg.start > cursor) {
			nodes.push(
				<div
					key={`xy-rsp-${cursor}-${seg.start}`}
					aria-hidden
					className="pointer-events-none"
					style={{height: (prefix[seg.start] ?? 0) - (prefix[cursor] ?? 0)}}
				/>,
			);
		}
		for (let i = seg.start; i < seg.end; i += 1) {
			nodes.push(renderRound(i, {bypassRoundMountIo: true}));
		}
		cursor = seg.end;
	}
	if (cursor < count) {
		nodes.push(
			<div
				key={`xy-rsp-${cursor}-end`}
				aria-hidden
				className="pointer-events-none"
				style={{height: (prefix[count] ?? 0) - (prefix[cursor] ?? 0)}}
			/>,
		);
	}
	return <>{nodes}</>;
}
