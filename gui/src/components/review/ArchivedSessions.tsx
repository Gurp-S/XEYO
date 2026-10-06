import {useMemo, useState} from 'react';
import {Folder, MoreHorizontal} from 'lucide-react';
import {useNavigate} from 'react-router-dom';
import {useChatStore} from '@/stores/chatStore';
import {useSettingsStore} from '@/stores/settingsStore';
import {openSession, pageViewFromPath} from '@/lib/appNav';
import {toast} from '@/lib/toast';
import {buildSessionMenuItems} from '../sidebar/SessionBits';
import {confirmSessionDelete} from '@/lib/confirmSessionDelete';
import {showContextMenu} from '../ui/ContextMenu';

export function ArchivedSessions() {
 const sessions = useChatStore(s => s.sessions);
 const spaces = useChatStore(s => s.spaces);
 const restore = useChatStore(s => s.restoreSession);
 const remove = useChatStore(s => s.removeSession);
 const navigate = useNavigate();
 const [busy, setBusy] = useState<string | null>(null);
 const run = async (id: string, action: () => Promise<unknown>) => {
  setBusy(id);
  try { await action(); } catch (error) { toast.error(error instanceof Error ? error.message : '会话操作失败'); }
  finally { setBusy(null); }
 };
 const groups = useMemo(() => {
  const grouped = new Map<string, typeof sessions>();
  for (const session of sessions.filter(s => s.archived).sort((a,b) => b.updatedAt - a.updatedAt)) {
   const key = session.spaceId || '';
   const group = grouped.get(key) ?? [];
   group.push(session); grouped.set(key, group);
  }
  return Array.from(grouped, ([id, items]) => ({id,items,name: spaces.find(s => s.id === id)?.name ?? (id ? '未载入的工作区' : '独立对话')}));
 }, [sessions, spaces]);
 return <section className="xy-settings-archive"><h3 className="xy-section-label">归档对话</h3>{groups.length ? groups.map(group => <details className="xy-archive-project" key={group.id} open><summary><Folder size={14}/>{group.name}<small>{group.items.length} 个对话</small></summary>{group.items.map(session => <div key={session.id}>
  <span><button className="xy-archive-title" onClick={() => {useSettingsStore.getState().closeSettings(); void openSession(session.id);}}>{session.title}</button><small>{spaces.find(s => s.id === session.spaceId)?.name ?? '独立对话'}</small></span>
  <button disabled={busy !== null} onClick={() => void run(session.id, () => restore(session.id))}>{busy===session.id ? '处理中…' : '恢复'}</button>
  <button disabled={busy !== null} aria-label={`归档会话操作：${session.title}`} onClick={e => showContextMenu(e, buildSessionMenuItems(session, {
   onRestore: () => void run(session.id, () => restore(session.id)),
   onDelete: () => {void (async () => {
    if (!(await confirmSessionDelete(session.title))) return;
    await run(session.id, async () => {
     const wasActive = useChatStore.getState().activeId === session.id;
     await remove(session.id);
     if (wasActive && !pageViewFromPath(window.location.pathname)) {
      const next = useChatStore.getState().activeId;
      if (next) await openSession(next); else navigate('/');
     }
    });
   })();},
  }), '归档会话')}><MoreHorizontal size={16}/></button>
 </div>)}</details>) : <p>没有已归档的会话。</p>}</section>;
}

