import {useEffect, useRef, useState} from 'react';
import {Compass, Pause, Play, Pencil, Trash2} from 'lucide-react';
import type {GoalSnapshot} from '@/lib/api/goals';
import {runGoalAction} from '@/lib/goalMutations';
import {DockTextEditor} from './DockTextEditor';

export function GoalDockCard({sessionId,goal,archived}: {sessionId:string;goal:GoalSnapshot;archived:boolean}) {
	const [editor,setEditor]=useState<{text:string;revision:number}|null>(null);
	const [pending,setPending]=useState(false);
	const [error,setError]=useState('');
	const [conflict,setConflict]=useState<GoalSnapshot|null>(null);
	const flight=useRef(false);
	const alive=useRef(true);
	useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
	const act=async(action:'pause'|'resume'|'drop'|'edit')=>{
		if(flight.current||archived)return;
		flight.current=true;setPending(true);setError('');
		try {
			const result=await runGoalAction(sessionId,action,{goal_id:goal.goal_id,...(action==='edit'&&editor ? {text:editor.text.trim(),revision:editor.revision}: {})});
			if(!alive.current)return;
			if(!result||!result.ok){
				const current=result&&!result.ok?result.conflict:null;
				setConflict(current);
				setError(current?'目标已被更新，你的修改尚未保存。':`操作未生效：${result&&!result.ok?result.message:'目标已变化'}`);
				return;
			}
			setEditor(null);setConflict(null);
		}catch {if(alive.current)setError('操作未保存，连接恢复后可重试。');}
		finally{flight.current=false;if(alive.current)setPending(false);}
	};
	const phase=goal.status==='paused'?'已暂停':goal.status==='blocked'?'受阻':'进行中';
	return <section className="xy-task-goal" data-goal-bar="" aria-label="Session goal" aria-busy={pending}>
		<header><Compass size={16}/><strong>目标</strong><span className={`xy-goal-phase is-${goal.status}`}>{phase}</span>
			{!editor&&<div className="xy-goal-actions">
				{goal.status==='active'&&<button type="button" disabled={pending||archived} aria-label="暂停" title="暂停目标" onClick={()=>void act('pause')}><Pause size={14}/><span>暂停</span></button>}
				{goal.status==='paused'&&<button type="button" disabled={pending||archived} aria-label="恢复" title="恢复目标" onClick={()=>void act('resume')}><Play size={14}/><span>恢复</span></button>}
				<button type="button" disabled={pending||archived} aria-label="编辑目标" onClick={()=>{setEditor({text:goal.text||goal.title,revision:goal.revision});setError('');setConflict(null);}}><Pencil size={14}/><span>编辑</span></button>
				<button type="button" disabled={pending||archived} aria-label="清除目标" title="清除目标" onClick={()=>void act('drop')}><Trash2 size={14}/></button>
			</div>}
		</header>
		{editor?<>
			<DockTextEditor label="目标内容" value={editor.text} pending={pending} error={error} onChange={text=>setEditor({...editor,text})} onSave={()=>void act('edit')} onCancel={()=>{setEditor(null);setError('');setConflict(null);}} saveLabel="保存目标"/>
			{conflict&&<div className="xy-goal-conflict"><p>最新目标</p><pre>{conflict.text||conflict.title}</pre><button type="button" onClick={()=>{setEditor({text:conflict.text||conflict.title,revision:conflict.revision});setConflict(null);setError('');}}>使用最新内容</button><button type="button" onClick={()=>{setEditor({...editor,revision:conflict.revision});setConflict(null);setError('');}}>保留我的修改继续编辑</button></div>}
		</>:<>
			<details className="xy-goal-objective"><summary>{goal.text||goal.title||'未命名目标'}</summary></details>
			{goal.status==='blocked'&&goal.blocked_reason&&<p className="xy-dock-error">{goal.blocked_reason}</p>}
			{error&&<p className="xy-dock-error" role="alert">{error}</p>}
		</>}
	</section>;
}
