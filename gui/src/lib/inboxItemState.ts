export type InboxItemState = 'queued' | 'delivering' | 'syncing' | 'stuck';

/** Only messages that have not entered delivery can be edited or cancelled. */
export function canMutateInboxItem(state: InboxItemState): boolean {
	return state === 'queued' || state === 'stuck';
}
