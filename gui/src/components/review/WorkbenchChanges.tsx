import {useEffect, useState} from 'react';
import {GitBranch, RefreshCw} from 'lucide-react';
import {gitStatus, type GitStatusResult} from '@/lib/api';
import {useChatStore} from '@/stores/chatStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {useExplorerStore} from '@/stores/explorerStore';
import {openChangedReview} from '../FilesChanged';
import {useWorkbenchChanges} from './useWorkbenchChanges';
import {WorkbenchRoundSelector} from './WorkbenchRoundSelector';
import type {ChangedFile} from '@/lib/toolActivity';

export function WorkbenchChanges() {
 const sessionId=useChatStore(s=>s.activeId);
 const [round,setRound]=useState('');
 const changed=useWorkbenchChanges(round || undefined);
 useEffect(()=>{setRound('');},[sessionId]);
 const root=useChatStore(s=>s.spaces.find(space=>space.id===s.activeSpaceId)?.rootPath ?? '');
 const open=useWorkspaceStore(s=>s.open);
 const selected=useExplorerStore(s=>s.reviewDiff?.path);
 const [scope,setScope]=useState<'turn'|'git'>('turn');
 const [status,setStatus]=useState<GitStatusResult | null>(null);
 const [error,setError]=useState('');
 const [loading,setLoading]=useState(false);
 const [revision,setRevision]=useState(0);
 useEffect(()=>{setStatus(null);setError('');setScope('turn');},[root]);
 useEffect(()=>{
  if(!root || !open)return;
  let current=true;
  const load=async()=>{
   setLoading(true);
   const results=await Promise.allSettled([gitStatus(root)]);
   if(!current)return;
   if(results[0].status==='fulfilled'){setStatus(results[0].value);setError('');}else setError(String(results[0].reason));
   setLoading(false);
  };
  void load();const timer=window.setInterval(()=>void load(),5000);
  return()=>{current=false;window.clearInterval(timer);};
 },[root,open,revision]);
 const gitFiles:ChangedFile[]=Array.from(new Map([...(status?.staged??[]),...(status?.unstaged??[]),...(status?.untracked??[])].map(file=>[file.path,{path:file.path,name:file.path.replace(/\\/g,'/').split('/').at(-1)??file.path,add:0,del:0}])).values());
 const files=scope==='turn'?changed:gitFiles;
 return <div className={`xy-work-changes ${selected ? 'has-diff' : ''}`}>
  <header className="xy-work-title"><h2>更改</h2><div className="xy-work-segment">{(['turn','git'] as const).map(value=><button key={value} aria-pressed={scope===value} onClick={()=>{useExplorerStore.getState().closePreview();setScope(value);}}>{value==='turn'?'本轮':'Git'}</button>)}</div><button aria-label="刷新改动" disabled={loading} onClick={()=>setRevision(v=>v+1)}><RefreshCw size={13}/></button></header>
  {scope==='turn' && <WorkbenchRoundSelector value={round} onChange={id=>{useExplorerStore.getState().closePreview();setRound(id);}}/>}
  {!!files.length && <><div className="xy-work-list-heading"><span>{files.length} 个文件 · {scope==='turn'?'当前会话':status?.branch ?? '工作区'}</span>{scope==='turn' && <span><small className="text-ok">+{files.reduce((n,f)=>n+f.add,0)}</small> <small className="text-danger">−{files.reduce((n,f)=>n+f.del,0)}</small></span>}</div><div className="xy-work-change-list">{files.map(file=><button key={file.path} title={file.path} className={`xy-work-change-row ${file.path===selected?'is-selected':''}`} onClick={()=>void openChangedReview(file)}><small>{file.created ? 'A' : 'M'}</small><span>{file.name}</span>{scope==='turn' && <><small className="text-ok">+{file.add}</small><small className="text-danger">−{file.del}</small></>}</button>)}</div></>}
  {!files.length && <div className="xy-work-empty"><GitBranch size={23}/><strong>{scope==='turn'?'本轮还没有文件改动':loading?'正在读取工作区状态':error?'工作区状态读取失败':status?.repo===false?'当前工作区不是 Git 仓库':'工作区没有文件改动'}</strong><p>{scope==='turn'?'改动会在实际修改后显示。':error}</p></div>}
 </div>;
}
