export type InboxItemState = 'queued' | 'delivering' | 'syncing' | 'stuck';

/** Only messages that have not entered delivery can be edited or cancelled. */
export function canMutateInboxItem(state: InboxItemState): boolean {
	return state === 'queued' || state === 'stuck';
}

export function assignInboxQueuePositions<T extends {state: InboxItemState}>(
	items: T[],
): Array<T & {position: number}> {
	let nextQueuePosition = 1;
	return items.map(item => ({
		...item,
		position: item.state === 'queued' ? nextQueuePosition++ : 0,
	}));
}
