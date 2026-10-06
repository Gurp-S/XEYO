import {useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {Folder, GitBranch, Globe, History, GitCommitHorizontal, Map as MapIcon, Maximize2, Minimize2, PanelRightClose, Plus, Terminal, FileText, X} from 'lucide-react';
import type {WorkspaceSection, WorkspaceTool} from '@/stores/workspaceStore';
import {useExplorerStore, type ReviewDiff} from '@/stores/explorerStore';
import {useChatStore} from '@/stores/chatStore';
import {useWorkspaceStore} from '@/stores/workspaceStore';
import {openContextMenu} from '../ui/ContextMenu';
import {WorkbenchView} from './WorkbenchView';

type Tab = {key:string; name:string; kind:'tree'|'tool'|'file'; value:string; review?:ReviewDiff};
const baseTabs: Tab[] = [
 {key:'files',name:'文件',kind:'tree',value:'files'},
 {key:'history',name:'更改',kind:'tree',value:'history'},
 {key:'git',name:'Git',kind:'tree',value:'git'},
];
const tools: [WorkspaceTool,string][] = [['terminal','终端'],['browser','浏览器'],['history','命令记录'],['commits','提交记录']];
const toolIcons = {terminal:Terminal,browser:Globe,history:History,commits:GitCommitHorizontal,map:MapIcon,git:GitBranch};

export function ReviewWorkspaceNav({active, activeTool, hasContent, onTree, onTool, onClose, showExperimental, children}: {
 active: WorkspaceSection; activeTool: WorkspaceTool | null; hasContent: boolean;
 onTree: (key: WorkspaceSection) => void; onTool: (key: WorkspaceTool | null) => void;
 onClose: () => void; showExperimental: boolean; children: ReactNode;
}) {
 const {split,expanded,toggleExpanded,closeFile} = useContext(WorkbenchView);
 const path = useExplorerStore(s=>s.selectedPath);
 const review = useExplorerStore(s=>s.reviewDiff);
 const space = useChatStore(s=>s.activeSpaceId);
 const [tabs,setTabs] = useState<Tab[]>(baseTabs.slice(0,2));
 const tabRow = useRef<HTMLDivElement>(null);
 const dragged = useRef<string | null>(null);
 const filePath = review ? null : path;
 useEffect(()=>{if(review) useWorkspaceStore.getState().setActive('history');},[review]);
 const current: Tab = filePath ? {key:`file:${filePath}`,name:filePath.replace(/\\/g,'/').split('/').at(-1) || filePath,kind:'file',value:filePath,review:review ?? undefined} : activeTool ? {key:`tool:${activeTool}`,name:tools.find(t=>t[0]===activeTool)?.[1] ?? activeTool,kind:'tool',value:activeTool} : baseTabs.find(t=>t.value===active) ?? baseTabs[0];
 useEffect(()=>setTabs(baseTabs.slice(0,2)),[space]);
 useEffect(()=>{
  setTabs(previous=>previous.some(t=>t.key===current.key) ? previous.map(t=>t.key===current.key ? current : t) : [...previous,current]);
  requestAnimationFrame(()=>tabRow.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest',inline:'nearest'}));
 },[current.key,review,space]);
 const select = (tab:Tab) => {
  if(tab.kind==='tree') onTree(tab.value as WorkspaceSection);
  else if(tab.kind==='tool') onTool(tab.value as WorkspaceTool);
  else {
   onTool(null);
   const explorer=useExplorerStore.getState();
   if(tab.review) void explorer.openReview(tab.review); else void explorer.openFile(tab.value);
  }
 };
 const close = async (tab:Tab) => {
  if(tab.kind==='file' && current.key===tab.key && !(await closeFile())) return;
  const index=tabs.findIndex(t=>t.key===tab.key);
  const rest=tabs.filter(t=>t.key!==tab.key);
  if (!rest.length) { onClose(); return; }
  setTabs(rest);
  if(current.key===tab.key) select(rest[Math.min(index,rest.length-1)]);
 };
 return <section className="xy-review-workspace-nav" aria-label="工作区导航">
  <header>
   <div ref={tabRow} role="tablist" aria-label="工作区视图">
    {tabs.map(tab=>{
     const Icon=tab.kind==='file' ? FileText : tab.kind==='tool' ? toolIcons[tab.value as WorkspaceTool] : tab.value==='files' ? Folder : GitBranch;
     return <div key={tab.key} className={`xy-work-tab ${current.key===tab.key ? 'is-active' : ''}`} draggable onDragStart={()=>{dragged.current=tab.key;}} onDragEnd={()=>{dragged.current=null;}} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();const key=dragged.current; if(!key || key===tab.key) return;setTabs(previous=>{const next=previous.filter(t=>t.key!==key);const source=previous.find(t=>t.key===key);if(source) next.splice(next.findIndex(t=>t.key===tab.key),0,source);return next;});}}>
      <button role="tab" aria-selected={current.key===tab.key} title={tab.value} onClick={()=>select(tab)}><Icon size={13}/><span>{tab.name}</span></button>
      <button className="xy-work-tab-close" aria-label={`关闭标签：${tab.name}`} onClick={()=>void close(tab)}><X size={12}/></button>
     </div>;
    })}
   </div>
   <button title="打开标签" aria-label="更多工作区工具" onClick={e=>{
    const rect=e.currentTarget.getBoundingClientRect();
    openContextMenu({x:rect.right-180,y:rect.bottom+6,ariaLabel:'工作区',items:[
     ...baseTabs.map(tab=>({kind:'action' as const,id:tab.key,label:tab.name,icon:tab.key==='files'?<Folder size={14}/>:<GitBranch size={14}/>,onSelect:()=>select(tab)})),
     {kind:'sep' as const},
     ...([...tools,...(showExperimental ? [['map','地图'] as [WorkspaceTool,string]] : [])]).map(([key,label])=>{const Icon=toolIcons[key];return {kind:'action' as const,id:`tool:${key}`,label,icon:<Icon size={14}/>,onSelect:()=>onTool(key)};}),
    ]});
   }}><Plus size={16}/></button>
      <button title={expanded ? '还原工作区' : '放大工作区'} aria-label={expanded ? '还原工作区' : '放大工作区'} onClick={toggleExpanded}>{expanded ? <Minimize2 size={15}/> : <Maximize2 size={15}/>}</button>
   <button title="收起工作区" aria-label="收起工作区" onClick={onClose}><PanelRightClose size={16}/></button>
  </header>
  {(!hasContent || split || Boolean(review)) && <div className={`xy-review-workspace-tree ${review ? 'has-review' : ''}`}>{children}</div>}
 </section>;
}
