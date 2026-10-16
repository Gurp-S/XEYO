import {workbenchLayout} from '@/lib/workbenchLayout';
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
	const {workspaceEff: fileWidth} = usePaneViewportClamp();
	const hostWidth = usePaneChatHostWidth();
 const activeTool = useWorkspaceStore(s => s.activeTool);
 const toolWidth = useSettingsStore(s => s.workspaceToolWidth);
 const {wide, focused, width} = workbenchLayout(activeTool, hostWidth, fileWidth, toolWidth);
 const [composerHeight, setComposerHeight] = useState(0);
 useLayoutEffect(() => {
  if (!open || !focused) return;
  const composer = ref.current?.parentElement?.querySelector<HTMLElement>('.xy-composer-stack');
  if (!composer) return;
  const sync = () => setComposerHeight(composer.getBoundingClientRect().height + 12);
  sync(); const observer = new ResizeObserver(sync); observer.observe(composer);
  return () => observer.disconnect();
 }, [open, focused]);
	const update = useSettingsStore(s => s.update);
	const ref = useRef<HTMLElement | null>(null);
	const [split, setSplit] = useState(false);
	const [expanded, setExpanded] = useState(false);
	const fileCloseRef = useRef<(() => Promise<boolean>) | null>(null);
	const registerFileClose = useCallback((handler: (()=>Promise<boolean>) | null) => {fileCloseRef.current=handler;},[]);
	const closeFile = useCallback(async()=>fileCloseRef.current ? fileCloseRef.current() : false,[]);
	useEffect(() => {
		if ((!expanded && !focused) || !open) return;
		pushEscLayer('review-workbench', () => expanded ? setExpanded(false) : useWorkspaceStore.getState().setActiveTool(null));
		return () => popEscLayer('review-workbench');
	}, [expanded, focused, open]);
	useEffect(() => {if (!open) setExpanded(false);}, [open]);
	const fileOpen = useExplorerStore(s => Boolean(s.selectedPath || s.reviewDiff || s.loadingFile));
	const toolOpen = useWorkspaceStore(s => Boolean(s.activeTool));
	const [host, setHost] = useState<HTMLElement | null>(null);
	useLayoutEffect(() => {setHost(ref.current?.closest<HTMLElement>('.xy-pane-chat-host') ?? null);},[]);
	const onWidth = useCallback((next: number) => update(wide ? {workspaceToolWidth: next} : {explorerWidth: next}),[update,wide]);
	const slotMax = useCallback(() => {
		const available = ref.current?.parentElement?.clientWidth ?? hostWidth;
		return activeTool ? available - CHAT_MIN_READABLE : window.innerWidth <= 640 ? available - 16 : Math.min(available * .52, available - CHAT_MIN_READABLE);
	}, [hostWidth, activeTool]);
	const collapse = useCallback(() => useWorkspaceStore.getState().setOpen(false), []);
	const resize = usePaneResize(width, onWidth, wide ? 480 : PANE_WIDTH_MIN, wide ? 960 : PANE_WIDTH_MAX, {invert:true, paneRef:ref, slotMax, constrainBaseToSlot:true, onCollapse:collapse});
	return <aside ref={ref} className={`xy-review-workbench ${wide ? 'is-wide-tool' : ''} ${expanded ? 'is-expanded' : focused ? 'is-tool-focused' : ''} ${resize.dragging ? 'xy-pane-dragging' : ''} ${shown ? 'is-shown' : ''} ${split && (fileOpen || toolOpen) ? 'is-split' : ''}`} aria-label="工作区" aria-hidden={!open} inert={!open} hidden={!open && !mounted} style={{width:open ? width : 0,flexBasis:open && !focused ? width : 0,...(focused && !expanded ? {bottom:composerHeight} : {})}}>
		{open && !expanded && !focused && <PaneResizeHandle edge="left" dragging={resize.dragging} label="调整工作区宽度" onMouseDown={resize.onResizeStart} onKeyDown={resize.onResizeKeyDown} value={resize.value} minValue={resize.minValue} maxValue={resize.maxValue} />}
		<WorkbenchView.Provider value={{split,expanded,toggleSplit:()=>setSplit(v=>!v),toggleExpanded:()=>setExpanded(v=>!v),closeFile,registerFileClose}}>
			<div className="xy-workbench-content" style={{width:expanded || focused ? '100%' : width}}><WorkbenchOverlayHost.Provider value={host}>{children}</WorkbenchOverlayHost.Provider></div>
		</WorkbenchView.Provider>
	</aside>;
}
