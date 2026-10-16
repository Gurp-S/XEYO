import {useEffect, useRef, useState} from 'react';
import {ArrowDown, ArrowUp, ChevronDown, ChevronUp, GripVertical, Pencil, Send, X, Zap} from 'lucide-react';
import {useChatUiStoreApi} from '@/stores/chatUiStore';
import {activeBackendSessionId, type InboxQueuedItem} from '@/stores/chat/preStoreHelpers';
import {captureInboxMutation} from '@/stores/chat/inboxMutationOwnership';
import {canEditInboxItem, canManuallyResumeInbox, canMutateInboxItem, canSteerInboxItem, prioritizeInboxPreview} from '@/lib/inboxItemState';
import {queueImageRefs} from '@/lib/inboxDockPresentation';
import {mediaUrl, steerInboxItem} from '@/lib/api';
import {resumeInboxUsingCurrentSettings} from '@/hooks/useQueuedRequestSettings';
import {type ChatRequestOptions} from '@/lib/api/core';
import {DockTextEditor} from './DockTextEditor';

type Props = {sessionId: string; items: InboxQueuedItem[]; archived: boolean; side: boolean; busy: boolean; options: ChatRequestOptions; onEditingChange?: (active: boolean) => void};

/** Queue presentation and editing are independent of the main composer draft. */
export function ComposerQueueDock({sessionId,items,archived,side,busy,options,onEditingChange}: Props) {
	const store = useChatUiStoreApi();
	const [expanded,setExpanded]=useState(()=>items.length===1);
	const [editing,setEditing]=useState<{id:string;text:string;original:string}|null>(null);
	const isEditing=Boolean(editing);
	useEffect(()=>{onEditingChange?.(isEditing);return()=>onEditingChange?.(false);},[isEditing,onEditingChange]);
	const [pending,setPending]=useState(false);
	const [error,setError]=useState('');
	const [dragged,setDragged]=useState<string|null>(null);
	const flight=useRef(false);
	const alive=useRef(true);
	useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
	useEffect(()=>{if(!items.length&&!editing)setExpanded(false);},[items.length,editing]);
	const queued=items.filter(item=>item.state==='queued');
	const run=async(action:()=>Promise<boolean>,message:string)=>{
		if(flight.current||archived)return false;
		const owner=captureInboxMutation(store.getState,sessionId);
		if(!owner.isCurrent())return false;
		flight.current=true;setPending(true);setError('');
		try {
			const ok=await action();
			if(alive.current&&owner.isCurrent()&&!ok)setError(message);
			return ok&&alive.current&&owner.isCurrent();
		}catch {if(alive.current)setError(message);return false;}
		finally {flight.current=false;if(alive.current)setPending(false);}
	};
	const save=async()=>{
		if(!editing)return;
		const item=(store.getState().inboxBySession[sessionId]??[]).find(item=>item.queue_id===editing.id);
		if(!item||!canEditInboxItem(item.state,archived)){setError('消息已开始投递，修改尚未保存。可复制内容后重新发送。');return;}
		const text=editing.text.trim();
		if(text===editing.original){setEditing(null);return;}
		if(await run(()=>store.getState().editInboxItem(sessionId,editing.id,text),'修改未保存，消息可能已开始投递。'))setEditing(null);
	};
	const reorder=(source:string,target:string)=>{
		if(pending||editing||archived||source===target)return;
		const expected=queued.map(item=>item.queue_id);
		const from=expected.indexOf(source),to=expected.indexOf(target);
		if(from<0||to<0)return;
		const order=[...expected];order.splice(to,0,order.splice(from,1)[0]);
		void run(()=>store.getState().reorderInboxItems(sessionId,expected,order),'队列已变化或顺序未保存，请按最新列表重试。');
	};
	const deliver=(id?:string,steer=false)=>void run(async()=>{
		const backend=activeBackendSessionId(store.getState().historyById,sessionId);
		const ok=steer&&id ? await steerInboxItem(backend,id) : await resumeInboxUsingCurrentSettings(backend,options,id);
		await store.getState().refreshInbox(sessionId);return ok;
	},'投递未生效，请稍后重试。');
	if(!items.length&&!editing)return null;
	const visible=expanded||Boolean(editing);
	return <section className="xy-task-queue" data-queue-dock="" aria-label="消息队列" aria-busy={pending}>
		<header><button type="button" className="xy-task-queue-heading" aria-expanded={visible} onClick={()=>setExpanded(v=>!v)} disabled={Boolean(editing)||pending}>
			<strong>待发送消息</strong><span>{queued.length} 条待发送{items.some(item=>item.state==='stuck') ? ` · ${items.filter(item=>item.state==='stuck').length} 条失败` : ''}{items.some(item=>item.state==='delivering'||item.state==='syncing') ? ' · 投递中' : ''}</span>{visible?<ChevronDown size={15}/>:<ChevronUp size={15}/>}</button>
			{canManuallyResumeInbox(archived,busy,items)&&<button type="button" className="xy-dock-text-action" disabled={pending} onClick={()=>deliver()}>继续投递</button>}
		</header>
		{error&&!editing&&<p className="xy-dock-error" role="alert">{error}</p>}
		{editing&&<DockTextEditor label="编辑排队消息" value={editing.text} maxLength={2000} pending={pending} error={error} onChange={text=>setEditing({...editing,text})} onSave={()=>void save()} onCancel={()=>{setEditing(null);setError('');}}/>}
		{visible&&<ol className="xy-task-queue-list">{prioritizeInboxPreview(items).map(item=>{
			const index=queued.findIndex(entry=>entry.queue_id===item.queue_id);
			const mutable=canMutateInboxItem(item.state)&&!archived;
			const movable=item.state==='queued'&&!archived&&!pending&&!editing;
			return <li key={item.queue_id} data-queue-id={item.queue_id} className={dragged===item.queue_id?'is-dragging':''}
				onDragOver={e=>{if(movable&&dragged)e.preventDefault();}} onDrop={e=>{e.preventDefault();if(dragged)reorder(dragged,item.queue_id);setDragged(null);}}>
				<button type="button" className="xy-queue-drag" aria-label={`拖动第 ${index+1} 条消息排序`} disabled={!movable} draggable={Boolean(movable)} onDragStart={e=>{setDragged(item.queue_id);e.dataTransfer.setData('text/plain',item.queue_id);e.dataTransfer.effectAllowed='move';}} onDragEnd={()=>setDragged(null)}><GripVertical size={15}/></button>
				<div className="xy-task-queue-content"><div className="xy-task-queue-meta">{item.state==='queued'?`第 ${index+1} 位`:item.state==='stuck'?'投递失败':item.state==='syncing'?'正在同步回复':'正在投递'}</div><p>{item.text}</p>
				{queueImageRefs(item.media_refs).length>0&&<span className="xy-queue-attachments">{queueImageRefs(item.media_refs).map(ref=><img key={ref} className="xy-queue-thumb" src={mediaUrl(ref)} alt="排队消息图片" loading="lazy"/>)}</span>}</div>
				<div className="xy-task-queue-actions">
					{index>=0&&<><button type="button" title="上移" aria-label="上移消息" disabled={!movable||index===0} onClick={()=>reorder(item.queue_id,queued[index-1].queue_id)}><ArrowUp size={14}/></button><button type="button" title="下移" aria-label="下移消息" disabled={!movable||index===queued.length-1} onClick={()=>reorder(item.queue_id,queued[index+1].queue_id)}><ArrowDown size={14}/></button></>}
					{mutable&&<button type="button" title="编辑消息" aria-label="编辑消息" disabled={pending||Boolean(editing)} onClick={()=>{setEditing({id:item.queue_id,text:item.text,original:item.text});setExpanded(true);setError('');}}><Pencil size={14}/></button>}
					{item.state==='stuck'&&!archived&&<button type="button" title="重新投递" aria-label="重新投递" disabled={pending||Boolean(editing)} onClick={()=>deliver(item.queue_id)}><Send size={14}/></button>}
					{busy&&canSteerInboxItem(item.state,archived,side)&&<button type="button" title="本轮继续时插入" aria-label="本轮继续时插入" disabled={pending||Boolean(editing)} onClick={()=>deliver(item.queue_id,true)}><Zap size={14}/></button>}
					<button type="button" title="取消排队" aria-label="取消排队" disabled={!mutable||pending||Boolean(editing)} onClick={()=>void run(()=>store.getState().cancelInboxItem(sessionId,item.queue_id),'取消未生效，消息可能已开始投递。')}><X size={14}/></button>
				</div>
			</li>;
		})}</ol>}
	</section>;
}
