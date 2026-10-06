import {
	useCallback,
	useEffect,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
	type RefObject,
} from 'react';
import {isSmoothnessOn, useSettingsStore} from '@/stores/settingsStore';

/**
 * 拖拽分割条。
 *
 * 语义说明：`width`/`min`/`max`/`onWidth` 操作的是“基础宽”（如 previewWidth），
 * 而面板槽的显示宽可能基于它做线性加成（FilePreview / WorkspaceToolPanel 在
 * “收起右边内容”时会把隐藏的树导航宽度加进来：displayWidth = base + explorerWidth）。
 * 拖拽期间直接写 DOM 的宽与连续钳制都必须建立在槽宽域上，否则加到把面板
 * 拖出窗口（小窗口下聊天区被压到下限后继续给面板加宽，槽宽 + 树宽 > 窗口宽）。
 *
 * 因此：
 * - `slotOf(base)` 把基础宽映射为槽宽（恒等时行为与旧版一致）；
 * - `slotMax()` 返回该槽允许的最大显示宽（如窗口可用宽），缺省为无限。
 */
export function usePaneResize(
	width: number,
	onWidth: (next: number) => void,
	min: number,
	max: number,
	options?: {
		invert?: boolean;
		paneRef?: RefObject<HTMLElement | null>;
		slotOf?: (base: number) => number;
		slotMax?: () => number;
		chatMin?: number;
		/** Nested review panes store the visible width, without an invisible drag range. */
		constrainBaseToSlot?: boolean;
		/** Continue dragging past the minimum to collapse an auxiliary pane. */
		onCollapse?: () => void;
	},
) {
	const invert = options?.invert ?? false;
	const paneRef = options?.paneRef;
	const slotOf = options?.slotOf;
	const slotMax = options?.slotMax;
	const chatMin = options?.chatMin ?? 340;
	const constrainBaseToSlot = options?.constrainBaseToSlot ?? false;
	const onCollapse = options?.onCollapse;
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const [dragging, setDragging] = useState(false);
	const dragRef = useRef<{startX: number; startW: number} | null>(null);
	const liveRef = useRef(width);
	const effectiveSlotMax = useCallback(() => {
		if (slotMax) return slotMax();
		const pane = paneRef?.current;
		const row = pane?.parentElement;
		const chatHost = row?.querySelector<HTMLElement>(':scope > .xy-pane-chat-host');
		if (!row || !chatHost) return max;
		const children = Array.from(row.children);
		const fixedWidth = children
			.filter(child => child !== pane && child !== chatHost)
			.reduce((total, child) => total + child.getBoundingClientRect().width, 0);
		const gap = Number.parseFloat(window.getComputedStyle(row).columnGap) || 0;
		return Math.max(
			min,
			row.clientWidth - fixedWidth - chatMin - gap * Math.max(0, children.length - 1),
		);
	}, [chatMin, max, min, paneRef, slotMax]);

	/** 基础宽映射到可见槽宽；视口钳制时保留用户设置的基础宽。 */
	const mapBase = useCallback(
		(base: number): {slot: number; base: number} => {
			const toSlot = slotOf ?? ((w: number) => w);
			const baseWidth = Math.min(max, Math.max(min, base));
			const baseMinSlot = Math.max(min, toSlot(min));
			const baseMaxSlot = Math.max(baseMinSlot, toSlot(max));
			const availableSlotMax = Math.max(
				min,
				Math.min(effectiveSlotMax(), baseMaxSlot),
			);
			// A translated slot can have a nominal minimum larger than the available
			// width (e.g. hidden tree width + preview minimum). Keep the visible floor
			// at the pane minimum, while retaining the user's base width under clamping.
			const slotMin = Math.min(baseMinSlot, availableSlotMax);
			const slot = Math.min(
				availableSlotMax,
				Math.max(slotMin, toSlot(baseWidth)),
			);
			return {slot, base: constrainBaseToSlot ? Math.min(baseWidth, slot) : baseWidth};
		},
		[slotOf, effectiveSlotMax, min, max, constrainBaseToSlot],
	);
	const {value, minValue, maxValue} = useMemo(
		() => ({
			value: mapBase(width).slot,
			minValue: mapBase(min).slot,
			maxValue: mapBase(max).slot,
		}),
		[mapBase, max, min, width],
	);
	const onResizeKeyDown = useCallback(
		(e: React.KeyboardEvent<HTMLDivElement>) => {
			const step = e.shiftKey ? 32 : 8;
			if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
				e.preventDefault();
				const direction = (e.key === 'ArrowRight' ? 1 : -1) * (invert ? -1 : 1);
				onWidth(mapBase(width + direction * step).base);
			} else if (e.key === 'Home') {
				e.preventDefault();
				onWidth(mapBase(min).base);
			} else if (e.key === 'End') {
				e.preventDefault();
				onWidth(mapBase(max).base);
			}
		},
		[mapBase, max, min, onWidth, width, invert],
	);

	const onResizeStart = useCallback(
		(e: React.MouseEvent) => {
			e.preventDefault();
			const initial = mapBase(width);
			liveRef.current = initial.base;
			dragRef.current = {startX: e.clientX, startW: initial.base};
			const pane = paneRef?.current;
			if (pane && smoothness) {
				pane.classList.add('xy-pane-dragging');
				pane.style.willChange = 'width';
			}
			setDragging(true);
		},
		[mapBase, paneRef, smoothness, width],
	);

	useLayoutEffect(() => {
		if (!dragging || !smoothness) {
			return;
		}
		const pane = paneRef?.current;
		if (!pane) {
			return;
		}
		const {slot} = mapBase(liveRef.current);
		const px = `${Math.round(slot)}px`;
		if (pane.style.width !== px) {
			pane.style.width = px;
		}
		if (pane.style.flexBasis !== px) {
			pane.style.flexBasis = px;
		}
		pane.style.setProperty('--xy-pane-w', px);
	}, [dragging, paneRef, smoothness, mapBase]);

	useEffect(() => {
		if (!dragging) {
			return;
		}
		const paint = (raw: number) => {
			if (onCollapse && raw < min - 32) {
				dragRef.current = null;
				setDragging(false);
				onCollapse();
				return;
			}
			const {slot, base} = mapBase(raw);
			liveRef.current = base;
			const pane = paneRef?.current;
			if (smoothness && pane) {
				const px = `${Math.round(slot)}px`;
				pane.style.width = px;
				pane.style.flexBasis = px;
				pane.style.setProperty('--xy-pane-w', px);
				pane.style.willChange = 'width';
				pane.classList.add('xy-pane-dragging');
			}
			// 让相邻聊天列与被直接改动的面板处于同一布局帧。
			// 上面的 RAF 节流把 React 工作限制在浏览器绘制节奏内，
			// 而不是每个鼠标事件都触发。
			onWidth(base);
		};
		let moveRaf = 0;
		let pendingX: number | null = null;
		const applyPending = () => {
			moveRaf = 0;
			const x = pendingX;
			pendingX = null;
			const d = dragRef.current;
			if (x == null || !d) {
				return;
			}
			const delta = x - d.startX;
			const raw = invert ? d.startW - delta : d.startW + delta;
			paint(raw);
		};
		const onMove = (e: MouseEvent) => {
			if (!dragRef.current) {
				return;
			}
			pendingX = e.clientX;
			if (!moveRaf) {
				moveRaf = requestAnimationFrame(applyPending);
			}
		};
		const onUp = () => {
			if (moveRaf) {
				cancelAnimationFrame(moveRaf);
				moveRaf = 0;
			}
			if (pendingX != null) {
				applyPending();
			}
			dragRef.current = null;
			const pane = paneRef?.current;
			if (pane) {
				pane.style.willChange = '';
				pane.classList.remove('xy-pane-dragging');
			}
			if (smoothness) {
				onWidth(liveRef.current);
			}
			setDragging(false);
		};
		document.body.style.cursor = 'col-resize';
		document.body.style.userSelect = 'none';
		window.addEventListener('mousemove', onMove);
		window.addEventListener('mouseup', onUp);
		return () => {
			if (moveRaf) {
				cancelAnimationFrame(moveRaf);
			}
			document.body.style.cursor = '';
			document.body.style.userSelect = '';
			window.removeEventListener('mousemove', onMove);
			window.removeEventListener('mouseup', onUp);
			const pane = paneRef?.current;
			if (pane) {
				pane.style.willChange = '';
				pane.classList.remove('xy-pane-dragging');
			}
		};
	}, [dragging, invert, mapBase, onWidth, paneRef, smoothness, onCollapse, min]);

	return {dragging, onResizeStart, onResizeKeyDown, value, minValue, maxValue};
}
