import type {ChatMessage} from './types';

/** Runtime inbox labels can expire; undelivered identity must survive reload. */
export function persistableMessage(message: ChatMessage): ChatMessage {
	const copy = {...message};
	if (message.role === 'user' && message.queueState) copy.localUndelivered = true;
	delete copy.queueState;
	return copy;
}
