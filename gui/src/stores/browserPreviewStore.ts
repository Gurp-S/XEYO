import {create} from 'zustand';

/** Agent / UI 下发的预览浏览器指令。 */
export type BrowserPreviewCmd =
	| {kind: 'nav'; url: string}
	| {kind: 'reload'}
	| {kind: 'back'}
	| {kind: 'fwd'}
	| {kind: 'ext'};

type BrowserPreviewState = {
	/** 当前已加载 URL（面板同步；ext 无 url 时用）。 */
	url: string | null;
	/** 单调递增；面板订阅后消费 cmd。 */
	seq: number;
	cmd: BrowserPreviewCmd | null;
	setUrl: (url: string | null) => void;
	dispatch: (cmd: BrowserPreviewCmd) => void;
};

export const useBrowserPreviewStore = create<BrowserPreviewState>(set => ({
	url: null,
	seq: 0,
	cmd: null,
	setUrl(url) {
		set({url});
	},
	dispatch(cmd) {
		set(s => ({cmd, seq: s.seq + 1}));
	},
}));
