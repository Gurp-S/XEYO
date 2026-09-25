export type InboxItemState = 'queued' | 'delivering' | 'syncing' | 'stuck';

/** Only messages that have not entered delivery can be edited or cancelled. */
export function canMutateInboxItem(state: InboxItemState): boolean {
	return state === 'queued' || state === 'stuck';
}

/** Editing queue text is a session mutation; archived sessions remain read-only. */
export function canEditInboxItem(state: InboxItemState, archived = false): boolean {
	return !archived && canMutateInboxItem(state);
}

/** Manual resume starts model work and is unavailable from an archived session. */
export function canManuallyResumeInbox(
	archived: boolean,
	busy: boolean,
	items: readonly {state: InboxItemState; autorun?: boolean}[],
): boolean {
	return !archived && !busy && items.some(item => item.state === 'queued' && item.autorun === false);
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

/** Keep actionable and in-flight messages ahead of transcript-sync receipts in a compact preview. */
export function prioritizeInboxPreview<T extends {state: InboxItemState}>(items: T[]): T[] {
	const priority: Record<InboxItemState, number> = {
		queued: 0,
		stuck: 1,
		delivering: 2,
		syncing: 3,
	};
	return items
		.map((item, index) => ({item, index}))
		.sort(
			(a, b) =>
				priority[a.item.state] - priority[b.item.state] || a.index - b.index,
		)
		.map(({item}) => item);
}
