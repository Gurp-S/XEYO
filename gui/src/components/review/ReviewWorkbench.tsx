import type {ReactNode} from 'react';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {useSettingsStore, PANE_WIDTH_MIN, PANE_WIDTH_MAX, isSmoothnessOn} from '@/stores/settingsStore';
import {usePresence} from '@/hooks/usePresence';
import {usePaneViewportClamp, usePaneChatHostWidth, CHAT_MIN_READABLE} from '@/hooks/paneViewportClamp';
import {PaneResizeHandle} from '../PaneResizeHandle';
import {usePaneResize} from '@/hooks/usePaneResize';
import {useRef, useCallback, useLayoutEffect, useState, useEffect} from 'react';
import {pushEscLayer, popEscLayer} from '@/lib/escStack';
import {WorkbenchOverlayHost} from './WorkbenchOverlay';
import {WorkbenchView} from './WorkbenchView';
import {useExplorerStore} from '@/stores/explorerStore';

export function ReviewWorkbench({children}: {children: ReactNode}) {
	const open = useWorkspaceStore(s => s.open);
	const smoothness = useSettingsStore(s => isSmoothnessOn(s.smoothness));
	const {mounted, shown} = usePresence(open, smoothness ? 320 : 0, smoothness ? 2 : 0);
	const {workspaceEff: width} = usePaneViewportClamp();
	const hostWidth = usePaneChatHostWidth();
	const update = useSettingsStore(s => s.update);
	const ref = useRef<HTMLElement | null>(null);
	const [split, setSplit] = useState(false);
	const [expanded, setExpanded] = useState(false);
	const fileCloseRef = useRef<(() => Promise<boolean>) | null>(null);
	const registerFileClose = useCallback((handler: (()=>Promise<boolean>) | null) => {fileCloseRef.current=handler;},[]);
	const closeFile = useCallback(async()=>fileCloseRef.current ? fileCloseRef.current() : false,[]);
	useEffect(() => {
		if (!expanded || !open) return;
		pushEscLayer('review-workbench', () => setExpanded(false));
		return () => popEscLayer('review-workbench');
	}, [expanded, open]);
	useEffect(() => {if (!open) setExpanded(false);}, [open]);
	const fileOpen = useExplorerStore(s => Boolean(s.selectedPath || s.reviewDiff || s.loadingFile));
	const toolOpen = useWorkspaceStore(s => Boolean(s.activeTool));
	const [host, setHost] = useState<HTMLElement | null>(null);
	useLayoutEffect(() => {setHost(ref.current?.closest<HTMLElement>('.xy-pane-chat-host') ?? null);},[]);
	const onWidth = useCallback((next: number) => update({explorerWidth: next}),[update]);
	const slotMax = useCallback(() => {
		const available = ref.current?.parentElement?.clientWidth ?? hostWidth;
		return window.innerWidth <= 640 ? available - 16 : Math.min(available * .52, available - CHAT_MIN_READABLE);
	}, [hostWidth]);
	const collapse = useCallback(() => useWorkspaceStore.getState().setOpen(false), []);
	const resize = usePaneResize(width, onWidth, PANE_WIDTH_MIN, PANE_WIDTH_MAX, {invert:true, paneRef:ref, slotMax, constrainBaseToSlot:true, onCollapse:collapse});
	return <aside ref={ref} className={`xy-review-workbench ${expanded ? 'is-expanded' : ''} ${resize.dragging ? 'xy-pane-dragging' : ''} ${shown ? 'is-shown' : ''} ${split && (fileOpen || toolOpen) ? 'is-split' : ''}`} aria-label="工作区" aria-hidden={!open} inert={!open} hidden={!open && !mounted} style={{width:open ? width : 0,flexBasis:open ? width : 0}}>
		{open && !expanded && <PaneResizeHandle edge="left" dragging={resize.dragging} label="调整工作区宽度" onMouseDown={resize.onResizeStart} onKeyDown={resize.onResizeKeyDown} value={resize.value} minValue={resize.minValue} maxValue={resize.maxValue} />}
		<WorkbenchView.Provider value={{split,expanded,toggleSplit:()=>setSplit(v=>!v),toggleExpanded:()=>setExpanded(v=>!v),closeFile,registerFileClose}}>
			<div className="xy-workbench-content" style={{width:expanded ? '100%' : width}}><WorkbenchOverlayHost.Provider value={host}>{children}</WorkbenchOverlayHost.Provider></div>
		</WorkbenchView.Provider>
	</aside>;
}
