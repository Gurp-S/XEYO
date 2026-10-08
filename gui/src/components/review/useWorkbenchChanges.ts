import {useMemo} from 'react';
import {useChatStore} from '@/stores/chatStore';
import {groupTranscript, latestUserTurnBoundary} from '@/lib/groupTranscript';
import {collectChangedFilesFromItems} from '@/lib/toolActivity';
import type {ChatMessage} from '@/lib/types';

const EMPTY: ChatMessage[] = [];

/** The latest delivered user request defines a round, regardless of tool order. */
export function useWorkbenchChanges(messageId?: string) {
 const messages = useChatStore(s => s.activeId ? s.messagesById[s.activeId] ?? EMPTY : EMPTY);
 return useMemo(() => {
  const boundary = latestUserTurnBoundary(messages);
  const chosen = messageId ? messages.findIndex(message=>message.id===messageId && message.role==='user') : -1;
  const start = chosen >= 0 ? chosen : boundary?.index ?? 0;
  const next = messages.findIndex((message,index)=>index>start && message.role==='user' && !message.queueState && !message.localUndelivered && !message.uiOnly);
  const blocks = groupTranscript(messages.slice(start, next < 0 ? undefined : next));
  return collectChangedFilesFromItems(blocks.flatMap(b => b.kind === 'turn' ? b.items : []));
 }, [messages,messageId]);
}
