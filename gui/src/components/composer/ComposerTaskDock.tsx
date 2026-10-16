import {useEffect,useId,useState,type ReactNode} from 'react';
import {usePendingAskForActiveSession,usePendingPermissionForActiveSession,usePendingPlanForActiveSession} from '@/hooks/usePendingForActiveSession';
import {useSessionGoalDockLive} from '../SessionGoalDock';
import {PermissionDialog} from '../PermissionDialog';
import {AskUserDialog} from '../AskUserDialog';
import {PlanDialog} from '../PlanDialog';
export function ComposerTaskDock({goal,queue,todo,hasQueue,hasTodo}:{goal:ReactNode;queue:(onEditingChange:(active:boolean)=>void)=>ReactNode;todo:ReactNode;hasQueue:boolean;hasTodo:boolean}) {
 const permission=usePendingPermissionForActiveSession(),ask=usePendingAskForActiveSession(),plan=usePendingPlanForActiveSession();
 const hasGoal=useSessionGoalDockLive();
 const [queueEditing,setQueueEditing]=useState(false);
 const [selected,setSelected]=useState('');const id=useId();
 const attention=[permission&&`permission:${permission.requestId}`,ask&&`ask:${ask.requestId}`,plan&&`plan:${plan.requestId}`].filter(Boolean).join('|');
 useEffect(()=>{if(attention) setSelected(attention.split(':')[0]);},[attention]);
 const slots=[{key:'permission',label:'批准',on:!!permission},{key:'ask',label:'提问',on:!!ask},{key:'plan',label:'计划',on:!!plan},{key:'goal',label:'目标',on:hasGoal},{key:'queue',label:'队列',on:hasQueue||queueEditing},{key:'todo',label:'待办',on:hasTodo}];
 const available=slots.filter(s=>s.on),current=available.some(s=>s.key===selected)?selected:available[0]?.key;
 const nodes:Record<string,ReactNode>={permission:<PermissionDialog visible={current==='permission'}/>,ask:<AskUserDialog/>,plan:<PlanDialog/>,goal,queue:queue(setQueueEditing),todo};
 return <div className="xy-task-dock" hidden={!available.length}>
 {available.length>1 && <div role="tablist" aria-label="当前任务" className="xy-task-dock-tabs">{available.map((s,index)=><button key={s.key} id={`${id}-${s.key}-tab`} role="tab" aria-selected={current===s.key} aria-controls={`${id}-${s.key}`} tabIndex={current===s.key?0:-1} onClick={()=>setSelected(s.key)} onKeyDown={e=>{const next=e.key==='ArrowRight'?(index+1)%available.length:e.key==='ArrowLeft'?(index+available.length-1)%available.length:e.key==='Home'?0:e.key==='End'?available.length-1:null;if(next!==null){e.preventDefault();setSelected(available[next].key);document.getElementById(`${id}-${available[next].key}-tab`)?.focus();}}}>{s.label}</button>)}</div>}
 {slots.map(s=><div key={s.key} id={`${id}-${s.key}`} role={available.length>1?'tabpanel':undefined} aria-label={s.label} hidden={current!==s.key} inert={current!==s.key} className="xy-task-dock-slot">{nodes[s.key]}</div>)}
 </div>;
}
