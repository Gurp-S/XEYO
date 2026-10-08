import type {ChatMessage} from '@/lib/types';
import {settleOrphanRunningTools} from './streamHelpers';

/** A stop timeout belongs to the tool rows observed at that stop. */
export function settleStoppedTools(messages: ChatMessage[], stoppedIds: Set<string>) {
	const settled = settleOrphanRunningTools(messages.filter(message => stoppedIds.has(message.id)));
	if (!settled.changed) return {messages, changed: false};
	const byId = new Map(settled.messages.map(message => [message.id, message]));
	return {messages: messages.map(message => byId.get(message.id) ?? message), changed: true};
}
