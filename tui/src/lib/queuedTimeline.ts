import type {TimelineItem} from '../types.js';
import type {LoadedMessage} from '../api/sse.js';

export function messagesToItems(messages: LoadedMessage[]): TimelineItem[] {
  return messages.filter(m => !m.isThought).map(m => {
    if (m.role === 'tool') return {
      id: m.id, kind: 'tool', name: m.toolName || 'tool', summary: m.toolInput || '',
      status: m.toolStatus === 'error' ? 'error' : 'completed', result: m.text,
      isError: m.toolStatus === 'error', toolUseId: m.toolUseId,
    };
    return {id: m.id, kind: m.role, text: m.text};
  });
}

/** 以服务端顺序为准，同时保留待投递的用户消息和本地备注。 */
export function mergeQueuedTimeline(
  local: TimelineItem[], server: TimelineItem[], removedIds: Set<string>,
): TimelineItem[] {
  const byId = new Map(local.map(item => [item.id, item]));
  const serverIds = new Set(server.map(item => item.id));
  const tools = new Set(server.flatMap(item => item.kind === 'tool' && item.toolUseId ? [item.toolUseId] : []));
  const extra = local.filter(item => !serverIds.has(item.id) && !removedIds.has(item.id) &&
    !(item.kind === 'tool' && item.toolUseId && tools.has(item.toolUseId)));
  const result = server.map(item => {
    const old = byId.get(item.id);
    return old?.kind === 'assistant' && item.kind === 'assistant'
      ? {...old, ...item, streaming: false} : item;
  });
  // 备注保持在其后首条服务端记录旁，排队中的用户消息置于末尾。
  for (const item of extra) {
    const index = local.indexOf(item);
    const next = item.kind === 'user' ? undefined : local.slice(index + 1).find(row => serverIds.has(row.id));
    const at = next ? result.findIndex(row => row.id === next.id) : -1;
    if (at < 0) result.push(item); else result.splice(at, 0, item);
  }
  return result;
}

export function appendAssistantDelta(
  items: TimelineItem[], id: string, text: string, previousId?: string,
): TimelineItem[] {
  let next = items;
  // 原生回合在首个增量到达前创建空占位行。
  if (previousId && previousId !== id) {
    next = items.flatMap(item => item.id === previousId && item.kind === 'assistant'
      ? item.text ? [{...item, streaming: false}] : [] : [item]);
  }
  const index = next.findIndex(item => item.id === id && item.kind === 'assistant');
  if (index >= 0) return next.map((item, i) => i === index && item.kind === 'assistant'
    ? {...item, text: item.text + text, streaming: true} : item);
  return [...next, {id, kind: 'assistant', text, streaming: true}];
}
