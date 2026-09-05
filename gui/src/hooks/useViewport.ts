import {useEffect, useState} from 'react';

export type Viewport = {
	width: number;
	height: number;
	/** 紧凑布局：窄窗口 */
	compact: boolean;
};

const COMPACT_MAX = 780;

function read(): Viewport {
	const width = window.innerWidth;
	const height = window.innerHeight;
	return {width, height, compact: width < COMPACT_MAX};
}

/** 跟踪窗口尺寸以实现响应式布局（rAF 节流）。 */
export function useViewport(): Viewport {
	const [vp, setVp] = useState(read);

	useEffect(() => {
		let raf = 0;
		const onResize = () => {
			cancelAnimationFrame(raf);
			raf = requestAnimationFrame(() => setVp(read()));
		};
		window.addEventListener('resize', onResize);
		return () => {
			cancelAnimationFrame(raf);
			window.removeEventListener('resize', onResize);
		};
	}, []);

	return vp;
}
