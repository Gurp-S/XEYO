import {createContext, useContext, useEffect, useRef} from 'react';

/** 功能面板顶栏副标题（各 Body 上报，顶栏只渲染一次）。 */
export const WorkspaceToolSubtitleContext = createContext<
	(text: string) => void
>(() => {});

export function usePanelSubtitle(text: string) {
	const set = useContext(WorkspaceToolSubtitleContext);
	const prev = useRef<string | null>(null);
	useEffect(() => {
		if (prev.current === text) {
			return;
		}
		prev.current = text;
		set(text);
	}, [set, text]);
	useEffect(() => {
		return () => {
			prev.current = null;
			set('');
		};
	}, [set]);
}
