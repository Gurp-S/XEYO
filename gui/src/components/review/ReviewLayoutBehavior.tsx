import {useEffect, useLayoutEffect, useState} from 'react';
import {useChatStore} from '@/stores/chatStore';
import {popEscLayer, pushEscLayer} from '@/lib/escStack';

/** Compact windows start with the workspace available; the navigation remains a drawer. */
export function ReviewLayoutBehavior() {
 const [compact,setCompact]=useState(()=>window.matchMedia('(max-width: 900px)').matches);
 const sidebarOpen=useChatStore(s=>s.sidebarOpen);
 useLayoutEffect(() => {
  const query=window.matchMedia('(max-width: 900px)');
  const update=()=>{setCompact(query.matches);if(query.matches)useChatStore.getState().setSidebarOpen(false);};
  update();
  query.addEventListener('change',update);
  return()=>query.removeEventListener('change',update);
 },[]);
 useEffect(()=>{
  if(!compact||!sidebarOpen)return;
  pushEscLayer('compact-sidebar',()=>useChatStore.getState().setSidebarOpen(false));
  return()=>popEscLayer('compact-sidebar');
 },[compact,sidebarOpen]);
 return compact&&sidebarOpen ? <button type="button" className="xy-compact-sidebar-backdrop" aria-label="关闭侧栏" onClick={()=>useChatStore.getState().setSidebarOpen(false)}/> : null;
}
