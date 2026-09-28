import {SIDE_SPACE_ID} from '@/lib/db';
import {useChatStore} from '@/stores/chatStore';

/**
 * 「当前会话」消失后的交接（页面视图背后的归档 / 删除）。
 *
 * 为什么要有这个模块：侧栏原本有四处各自手写「下一个该选谁」——归档的两条分支
 * （会话路由 / 页面视图）与删除的两条分支（主会话 / 侧聊）。页面视图不带会话 id，
 * 所以删除那两处算出的 `wasActiveRoute` 在 /usage|/plugins|/diagnostics 下恒为
 * false，分支根本不跑：交接被交给 `removeSession` 里的盲兜底（它按数组顺序取第一
 * 个未归档会话，会挑到别的工作区甚至侧聊），或者干脆什么都不留。
 * 此处把「选谁 + 怎么落地」收敛成一处，四处共用同一套规则。
 */

type HandoffCandidate = {
	id: string;
	spaceId: string;
	archived?: boolean;
};

/**
 * 消失会话（`gone`）之后，隐藏的那个会话位该落到谁身上。规则与既有分支逐条一致：
 * - 主会话：先同工作区的未归档会话，其次任意非侧聊的未归档会话；
 * - 侧聊：只交给另一条未归档侧聊；
 * - 都没有 → `null`：刻意回到新对话态，而不是把侧聊 / 别的工作区塞成当前会话。
 */
export function pickHandoffSessionId(
	sessions: readonly HandoffCandidate[],
	gone: {id: string; spaceId?: string},
): string | null {
	const isSide = gone.spaceId === SIDE_SPACE_ID;
	const visible = sessions.filter(s => s.id !== gone.id && !s.archived);
	if (isSide) {
		return visible.find(s => s.spaceId === SIDE_SPACE_ID)?.id ?? null;
	}
	return (
		visible.find(s => s.spaceId === gone.spaceId)?.id ??
		visible.find(s => s.spaceId !== SIDE_SPACE_ID)?.id ??
		null
	);
}

/**
 * 页面视图（用量 / 扩展 / 诊断）背后的当前会话已消失：把会话位换到下一个存活会话。
 *
 * 必须 `await` 且校验落点：发射即忘的 `void selectSession(next.id)` 一旦没落地
 * （reject、或 selectSession 对缺失会话直接早退），`closePageView` 就会落在
 * 已删除 / 已归档的 id 上。落不了地就退回 `null`（新对话态）——出口宁可空着，
 * 也不停在用户没有选过、且只读发不出去的会话上。
 */
export async function handoffHiddenActiveSession(gone: {
	id: string;
	spaceId?: string;
}): Promise<void> {
	const nextId = pickHandoffSessionId(
		useChatStore.getState().sessions,
		gone,
	);
	if (!nextId) {
		useChatStore.setState({activeId: null});
		return;
	}
	try {
		await useChatStore.getState().selectSession(nextId);
	} catch {
		/* 交给下面的落点校验兜住 */
	}
	const after = useChatStore.getState();
	const landed = after.sessions.find(s => s.id === after.activeId);
	if (!landed || landed.id !== nextId || landed.archived) {
		useChatStore.setState({activeId: null});
	}
}
