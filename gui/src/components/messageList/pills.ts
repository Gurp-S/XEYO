/**
 * Rewind cut-pill lookup, extracted from messageList/MessageList.tsx.
 * Pure helper: maps a round to its before/after rewind cut pills.
 */
import type {RewindPill} from '@/stores/rewindV3Store';
import type {Round} from './types';

export type RoundPills = {
	before: RewindPill | undefined;
	after: RewindPill | undefined;
};

export function findRoundPills(
	round: Round,
	cutPills: RewindPill[] | undefined,
): RoundPills {
	const before = cutPills?.find(p => p.afterMessageId === round.user?.id);
	if (before) {
		return {before, after: undefined};
	}
	const after = cutPills?.find(p =>
		round.rest.some(b => (b as {id?: string}).id === p.afterMessageId),
	);
	return {before: undefined, after};
}
