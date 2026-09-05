import {useEffect, useState} from 'react';

/** 在短暂退出阶段保持子节点挂载，以便 CSS 离开动画播放。 */
export function usePresence(
	open: boolean,
	exitMs = 160,
	enterRafs: 0 | 1 | 2 = 2,
) {
	const [mounted, setMounted] = useState(open);
	const [shown, setShown] = useState(open);

	useEffect(() => {
		if (open) {
			setMounted(true);
			if (enterRafs === 0) {
				setShown(true);
				return;
			}
			let inner = 0;
			const id = requestAnimationFrame(() => {
				if (enterRafs <= 1) {
					setShown(true);
					return;
				}
				inner = requestAnimationFrame(() => setShown(true));
			});
			return () => {
				cancelAnimationFrame(id);
				if (inner) {
					cancelAnimationFrame(inner);
				}
			};
		}
		setShown(false);
		const t = window.setTimeout(() => setMounted(false), exitMs);
		return () => window.clearTimeout(t);
	}, [open, exitMs, enterRafs]);

	return {mounted, shown};
}
