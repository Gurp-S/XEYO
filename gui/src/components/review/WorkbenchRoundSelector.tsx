import {RotateCcw} from 'lucide-react';
import {useChatStore} from '@/stores/chatStore';
import {useRewindV3Store} from '@/stores/rewindV3Store';
import {latestUserTurnBoundary} from '@/lib/groupTranscript';
import type {ChatMessage} from '@/lib/types';

const EMPTY:ChatMessage[]=[];

/** Reuses the existing rewind confirmation; this control never executes a restore. */
export function WorkbenchRoundSelector({value,onChange}:{value:string;onChange:(id:string)=>void}) {
 const sessionId=useChatStore(s=>s.activeId);
 const messages=useChatStore(s=>s.activeId?s.messagesById[s.activeId]??EMPTY:EMPTY);
 const requests=messages.filter(message=>message.role==='user' && !message.queueState && !message.localUndelivered && !message.uiOnly);
 const target=messages.find(message=>message.id===value) ?? latestUserTurnBoundary(messages)?.message;
 return <div className="xy-work-round-selector"><RotateCcw size={13}/><select aria-label="选择审查轮次" value={value} onChange={e=>onChange(e.target.value)}><option value="">本轮</option>{requests.slice(0,-1).reverse().map(message=><option key={message.id} value={message.id}>{message.text.replace(/\s+/g,' ').slice(0,40) || '历史轮次'}</option>)}</select>
  <button disabled={!target || !sessionId} onClick={()=>{if(target && sessionId)useRewindV3Store.getState().openDialog(sessionId,target.id,target.text,target.mediaRefs);}}>回溯文件</button>
 </div>;
}
