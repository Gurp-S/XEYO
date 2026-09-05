import {useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject} from 'react';
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
	},
) {
	const invert = options?.invert ?? false;
	const paneRef = options?.paneRef;
	const slotOf = options?.slotOf;
	const slotMax = options?.slotMax;
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const [dragging, setDragging] = useState(false);
	const dragRef = useRef<{startX: number; startW: number} | null>(null);
	const liveRef = useRef(width);

	/** 基础宽 → 槽宽 → 按槽宽域钳制 → 反解基础宽。 */
	const mapBase = useCallback(
		(base: number): {slot: number; base: number} => {
			const toSlot = slotOf ?? ((w: number) => w);
			const lo = Math.max(min, toSlot(min));
			let hi = Math.max(toSlot(max), lo);
			if (slotMax) {
				hi = Math.min(Math.max(slotMax(), lo), hi);
			}
			const slot = Math.min(hi, Math.max(lo, toSlot(base)));
			return {slot, base: slot - toSlot(0)};
		},
		[slotOf, slotMax, min, max],
	);

	const onResizeStart = useCallback(
		(e: React.MouseEvent) => {
			e.preventDefault();
			liveRef.current = width;
			dragRef.current = {startX: e.clientX, startW: width};
			const pane = paneRef?.current;
			if (pane && smoothness) {
				pane.classList.add('xy-pane-dragging');
				pane.style.willChange = 'width';
			}
			setDragging(true);
		},
		[paneRef, smoothness, width],
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
			const {slot, base} = mapBase(raw);
			liveRef.current = base;
			const pane = paneRef?.current;
			if (smoothness && pane) {
				const px = `${Math.round(slot)}px`;
				pane.style.width = px;
				pane.style.setProperty('--xy-pane-w', px);
				pane.style.willChange = 'width';
				pane.classList.add('xy-pane-dragging');
			}
			// Keep the sibling chat column in the same layout frame as the
			// directly-mutated pane. The RAF throttle above limits React work to
			// the browser's paint cadence instead of every mouse event.
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
		};
	}, [dragging, invert, mapBase, onWidth, paneRef, smoothness]);

	return {dragging, onResizeStart};
}
