import type {ChatApiMessage} from './api';
import type {ChatMessage} from './types';

/**
 * 将本地 transcript 映射为 OpenAI messages 供 BE hydrate。
 * - 跳过 UI-only 的 isThought / tool 行
 * - 合并相邻 assistant  prose，避免 GLM 等 API 报 messages 非法（1214）
 */
export function toApiMessages(msgs: ChatMessage[]): ChatApiMessage[] {
	const out: ChatApiMessage[] = [];
	for (const m of msgs) {
		if (m.isThought || m.uiOnly || m.role === 'tool') {
			continue;
		}
		const content =
			m.text.trim() ||
			(m.role === 'user' && m.mediaRefs?.length ? '请分析这些图片。' : '');
		if (!content) {
			continue;
		}
		if (m.role === 'user' || m.role === 'assistant') {
			const last = out[out.length - 1];
			if (m.role === 'assistant' && last?.role === 'assistant') {
				last.content = `${last.content}\n\n${content}`;
				continue;
			}
			out.push({
				role: m.role,
				content,
				id: m.id,
				...(m.mediaRefs?.length ? {media_refs: m.mediaRefs} : {}),
			});
		} else if (m.role === 'system') {
			out.push({role: 'system', content});
		}
	}
	return out;
}
