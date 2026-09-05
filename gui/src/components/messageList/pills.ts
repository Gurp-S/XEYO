/**
 * 回溯剪切药丸查找，从 messageList/MessageList.tsx 拆出。
 * 纯函数：将轮次映射到其前/后的回溯剪切药丸。
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
