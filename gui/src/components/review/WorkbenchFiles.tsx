import {useEffect, useState} from 'react';
import {ArrowUp, ChevronRight, FileText, Folder, RefreshCw, Search} from 'lucide-react';
import {useExplorerStore} from '@/stores/explorerStore';
import {useChatStore} from '@/stores/chatStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {filePathMenuItems} from '@/lib/contextMenus';
import {joinWorkspacePath} from '@/lib/workspaceOpen';
import {showContextMenu} from '../ui/ContextMenu';
import {openChangedReview} from '../FilesChanged';
import {useWorkbenchChanges} from './useWorkbenchChanges';

export function WorkbenchFiles() {
 const root = useChatStore(s=>s.spaces.find(space=>space.id===s.activeSpaceId)?.rootPath ?? '');
 const rootName = root.replace(/\\/g,'/').split('/').filter(Boolean).at(-1) ?? '工作区';
 const [directory,setDirectory] = useState('');
 const [query,setQuery] = useState('');
 const [busy,setBusy] = useState(false);
 const entries = useExplorerStore(s=>s.childrenByPath[directory]);
 const error = useExplorerStore(s=>s.directoryErrors[directory] ?? s.error);
 const changed = useWorkbenchChanges();
 useEffect(()=>{setDirectory('');setQuery('');},[root]);
 useEffect(()=>{
  let active=true;
  setBusy(true);
  const store=useExplorerStore.getState();
  void store.ensureRoot().then(()=>store.ensureDir(directory)).finally(()=>{if(active)setBusy(false);});
  return ()=>{active=false;};
 },[root,directory]);
 const move=(path:string)=>{setDirectory(path);setQuery('');};
 const visible=(entries ?? []).filter(entry=>entry.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())).slice().sort((a,b)=>Number(b.kind==='dir')-Number(a.kind==='dir') || a.name.localeCompare(b.name));
 const crumbs=directory.split('/').filter(Boolean);
 return <div className="xy-work-files">
  <div className="xy-work-pathbar"><div className="xy-work-breadcrumbs"><Folder size={14}/><button onClick={()=>move('')}>{rootName}</button>{crumbs.map((name,index)=><span key={index}><ChevronRight size={11}/><button onClick={()=>move(crumbs.slice(0,index+1).join('/'))}>{name}</button></span>)}</div>
   <button aria-label="上一级目录" disabled={!directory} onClick={()=>move(crumbs.slice(0,-1).join('/'))}><ArrowUp size={15}/></button>
   <button aria-label="刷新目录" disabled={busy || !root} onClick={()=>{
    setBusy(true);const store=useExplorerStore.getState();
    void store.invalidateDir(directory).then(()=>store.ensureDir(directory)).finally(()=>setBusy(false));
   }}><RefreshCw size={14}/></button>
  </div>
  <label className="xy-work-filter"><Search size={14}/><input aria-label="筛选当前目录" placeholder="筛选当前目录" value={query} onChange={e=>setQuery(e.target.value)}/></label>
  <div className="xy-work-list-heading"><span>名称</span><span>{visible.length} 项</span></div>
  {busy && !entries ? <p className="xy-work-note">正在读取目录…</p> : error ? <p className="xy-work-note">{error}</p> : !visible.length ? <p className="xy-work-note">{query ? '没有匹配的文件' : '目录为空'}</p> : <div className="xy-work-file-list">{visible.map(entry=>{
   const open=()=>entry.kind==='dir' ? move(entry.path) : void useExplorerStore.getState().openFile(entry.path);
   return <button key={entry.path} className="xy-work-file-row" onClick={open} onContextMenu={e=>showContextMenu(e,filePathMenuItems({entryPath:entry.path,entryName:entry.name,absolutePath:joinWorkspacePath(root,entry.path),kind:entry.kind==='dir'?'dir':'file',onOpen:open}),entry.name)}>
    {entry.kind==='dir' ? <Folder size={15}/> : <FileText size={15}/>}
    <span>{entry.name}</span>{entry.kind==='dir' && <ChevronRight size={12}/>}
   </button>;
  })}</div>}
  {!!changed.length && <section className="xy-work-resource"><header><span>本轮会话 · {changed.length} 个文件</span><button onClick={()=>{useExplorerStore.getState().closePreview();useWorkspaceStore.getState().setActive('history');}}>更改</button></header>{changed.slice(0,6).map(file=><button className="xy-work-change-row" key={file.path} onClick={()=>{useWorkspaceStore.getState().setActive('history');void openChangedReview(file);}}><span>{file.name}</span><small className="text-ok">+{file.add}</small><small className="text-danger">−{file.del}</small></button>)}</section>}
 </div>;
}
