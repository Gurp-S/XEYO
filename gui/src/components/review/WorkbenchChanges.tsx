import {useEffect, useState} from 'react';
import {GitBranch, RefreshCw} from 'lucide-react';
import {type GitStatusResult} from '@/lib/api';
import {useChatStore} from '@/stores/chatStore';
import {useWorkspaceVisible} from '@/hooks/useWorkspaceVisible';
import {useExplorerStore} from '@/stores/explorerStore';
import {openChangedReview} from '../FilesChanged';
import {useWorkbenchChanges} from './useWorkbenchChanges';
import {WorkbenchRoundSelector} from './WorkbenchRoundSelector';
import {readWorkspaceGit,workspaceGitFiles} from '@/lib/workspaceGit';
import {startVisiblePolling} from '@/lib/visiblePolling';

export function WorkbenchChanges() {
 const sessionId=useChatStore(s=>s.activeId);
 const [round,setRound]=useState('');
 const [scope,setScope]=useState<'turn'|'git'>('turn');
 const changed=useWorkbenchChanges(round || undefined,scope==='turn');
 useEffect(()=>{setRound('');},[sessionId]);
 const root=useChatStore(s=>s.spaces.find(space=>space.id===s.activeSpaceId)?.rootPath ?? '');
 const open=useWorkspaceVisible();
 const selected=useExplorerStore(s=>s.reviewDiff?.path);
 const [status,setStatus]=useState<GitStatusResult | null>(null);
 const [error,setError]=useState('');
 const [loading,setLoading]=useState(false);
 const [revision,setRevision]=useState(0);
 useEffect(()=>{setStatus(null);setError('');setScope('turn');},[root]);
 useEffect(()=>{
  if(!root || !open || scope !== 'git')return;
  let current=true;
  const load=async()=>{
   setLoading(true);
   const results=await Promise.allSettled([readWorkspaceGit(root)]);
   if(!current)return;
   if(results[0].status==='fulfilled'){setStatus(results[0].value);setError('');}else setError(String(results[0].reason));
   setLoading(false);
  };
  const stop=startVisiblePolling(load,5000);
  return()=>{current=false;stop();};
 },[root,open,revision,scope]);
 const gitFiles=workspaceGitFiles(status);
 const files=scope==='turn'?changed:gitFiles;
 return <div className={`xy-work-changes ${selected ? 'has-diff' : ''}`}>
  <header className="xy-work-title"><h2>更改</h2><div className="xy-work-segment">{(['turn','git'] as const).map(value=><button key={value} aria-pressed={scope===value} onClick={()=>{useExplorerStore.getState().closePreview();setScope(value);}}>{value==='turn'?'本轮':'Git'}</button>)}</div><button aria-label="刷新改动" disabled={loading} onClick={()=>setRevision(v=>v+1)}><RefreshCw size={13}/></button></header>
  {open && scope==='turn' && <WorkbenchRoundSelector value={round} onChange={id=>{useExplorerStore.getState().closePreview();setRound(id);}}/>}
  {scope==='git' && error && !!files.length && <p role="alert" className="xy-work-note">刷新失败，当前显示上次读取的状态。</p>}
  {!!files.length && <><div className="xy-work-list-heading"><span>{files.length} 个文件 · {scope==='turn'?'当前会话':status?.branch ?? '工作区'}</span>{scope==='turn' && <span><small className="text-ok">+{files.reduce((n,f)=>n+f.add,0)}</small> <small className="text-danger">−{files.reduce((n,f)=>n+f.del,0)}</small></span>}</div><div className="xy-work-change-list">{files.map(file=><button key={file.path} title={file.path} className={`xy-work-change-row ${file.path===selected?'is-selected':''}`} onClick={()=>void openChangedReview(file)}><small>{'gitStatus' in file ? file.gitStatus : file.created ? 'A' : 'M'}</small><span>{file.name}</span>{scope==='turn' && <><small className="text-ok">+{file.add}</small><small className="text-danger">−{file.del}</small></>}</button>)}</div></>}
  {!files.length && <div className="xy-work-empty"><GitBranch size={23}/><strong>{scope==='turn'?'本轮还没有文件改动':loading?'正在读取工作区状态':error?'工作区状态读取失败':status?.repo===false?'当前工作区不是 Git 仓库':!status?'正在读取工作区状态':'工作区没有文件改动'}</strong><p>{scope==='turn'?'改动会在实际修改后显示。':error}</p></div>}
 </div>;
}
