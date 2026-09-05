import {useCallback, useEffect, useRef, useState} from 'react';

/**
 * 展开/收起挂载：先挂载内容并完成一帧绘制，再开面板。
 * 高度过渡由 ExpandPanel 负责（长列表短切，避免 grid 0fr→1fr）。
 */
export function useExpandReveal(initialOpen = false) {
	const [open, setOpen] = useState(initialOpen);
	const [mounted, setMounted] = useState(initialOpen);
	const pendingOpenRef = useRef(false);

	useEffect(() => {
		if (!mounted || !pendingOpenRef.current) {
			return;
		}
		// 等浏览器画出 0fr + 内容后再开，避免与挂载同帧导致无展开动画。
		// Strict Mode 下 cleanup 会 cancel rAF，但 pending 仍为 true，重跑 effect 会再预约。
		const id = requestAnimationFrame(() => {
			if (!pendingOpenRef.current) {
				return;
			}
			pendingOpenRef.current = false;
			setOpen(true);
		});
		return () => cancelAnimationFrame(id);
	}, [mounted]);

	const expand = useCallback(() => {
		if (open) {
			return;
		}
		if (mounted) {
			setOpen(true);
			return;
		}
		pendingOpenRef.current = true;
		setMounted(true);
	}, [mounted, open]);

	const collapse = useCallback(() => {
		pendingOpenRef.current = false;
		setOpen(false);
	}, []);

	const toggle = useCallback(() => {
		if (open) {
			collapse();
		} else {
			expand();
		}
	}, [open, expand, collapse]);

	return {open, mounted, expand, collapse, toggle};
}
