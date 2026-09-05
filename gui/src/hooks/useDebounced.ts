import {useEffect, useState} from 'react';

/** 把频繁变化的值延后提交，避免每键都跑重渲染（如 Markdown 预览）。 */
export function useDebounced<T>(value: T, ms: number): T {
	const [debounced, setDebounced] = useState(value);
	useEffect(() => {
		if (ms <= 0) {
			setDebounced(value);
			return;
		}
		const t = window.setTimeout(() => setDebounced(value), ms);
		return () => window.clearTimeout(t);
	}, [value, ms]);
	if (ms <= 0) {
		return value;
	}
	return debounced;
}
