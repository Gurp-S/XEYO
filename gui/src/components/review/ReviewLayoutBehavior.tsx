import {useLayoutEffect} from 'react';
import {useChatStore} from '@/stores/chatStore';

/** Compact windows start with the workspace available; the navigation remains a drawer. */
export function ReviewLayoutBehavior() {
 useLayoutEffect(() => {
  if (window.matchMedia('(max-width: 900px)').matches) {
   useChatStore.getState().setSidebarOpen(false);
  }
 },[]);
 return null;
}
