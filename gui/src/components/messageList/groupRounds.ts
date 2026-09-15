/**
 * 归属：从 components/MessageList.tsx 巨石拆分而来（spec m1b: groupRounds，2026 拆分）。
 * 拆分脚本 dismantle-messagelist.cjs 已归档至 [过程]/legacy/，本文件此后为手工维护。
 * 代码块自 components/MessageList.tsx 原样迁移，行为不变。
 */
import {
	type TranscriptBlock,
} from '@/lib/groupTranscript';
import {
	type MultiAgentTaskView,
} from '@/lib/api';
import {
	Round,
} from './types';

export const NO_AGENT_TASKS: MultiAgentTaskView[] = [];

/**
 * 多 Agent 卡片 → 轮次锚定：任务落在「触发它的那条用户
 * 消息」所在轮。live 批 batchAt=SSE 到达时刻，必然晚于该用户消息、早于
 * 下一条用户消息；历史批取 meta.startedAt，同理。无锚点（异常）时兜底
 * 挂最早一轮。
 *
 * 纯函数：不变更入参数组元素（reuseRoundPrefix 跨渲染复用 round 对象，
 * RoundHost 以引用相等跳过重渲，原地修改会污染 memo），仅在任务实际
 * 变化的轮返回新对象，其余轮保持旧引用。
 */
export function roundsWithAgentTasks(
	rounds: Round[],
	tasks: MultiAgentTaskView[] | undefined,
): Round[] {
	if (rounds.length === 0) {
		return rounds;
	}
	if (!tasks || tasks.length === 0) {
		const dirty = rounds.some(r => r.agentTasks.length > 0);
		return dirty
			? rounds.map(r =>
					r.agentTasks.length === 0 ? r : {...r, agentTasks: NO_AGENT_TASKS},
				)
			: rounds;
	}

	const byIndex = new Map<number, MultiAgentTaskView[]>();
	// SSE 按批次序到达 / 后端 meta 按 startedAt 升序，这里排序仅为兜底乱序。
	const ordered =
		tasks.length > 1
			? [...tasks].sort((a, b) => (a.batchAt ?? 0) - (b.batchAt ?? 0))
			: tasks;
	let cursor = 0;
	for (const task of ordered) {
		const at = task.batchAt ?? Number.MAX_SAFE_INTEGER;
		while (
			cursor + 1 < rounds.length &&
			rounds[cursor + 1]!.user !== undefined &&
			(rounds[cursor + 1]!.user?.createdAt ?? Number.MAX_SAFE_INTEGER) <= at
		) {
			cursor += 1;
		}
		let idx = cursor;
		if (rounds[idx]!.user === undefined) {
			// 命中无用户消息的孤儿轮：向前回退到最近的用户轮。
			while (idx > 0 && rounds[idx]!.user === undefined) {
				idx -= 1;
			}
		}
		const list = byIndex.get(idx);
		if (list) {
			list.push(task);
		} else {
			byIndex.set(idx, [task]);
		}
	}

	if (byIndex.size === 0) {
		return rounds;
	}
	return rounds.map((round, index) => {
		const next = byIndex.get(index);
		if (!next || next.length === 0) {
			return round.agentTasks.length === 0
				? round
				: {...round, agentTasks: NO_AGENT_TASKS};
		}
		if (agentTasksSame(round.agentTasks, next)) {
			return round;
		}
		return {...round, agentTasks: next};
	});
}

/** 任务列表浅比较（uid+status+desc+result 足以覆盖卡片展示面）。 */
export function agentTasksSame(
	a: MultiAgentTaskView[],
	b: MultiAgentTaskView[],
): boolean {
	if (a === b) {
		return true;
	}
	if (a.length !== b.length) {
		return false;
	}
	for (let i = 0; i < a.length; i += 1) {
		const x = a[i]!;
		const y = b[i]!;
		if (
			x.uid !== y.uid ||
			x.status !== y.status ||
			x.desc !== y.desc ||
			x.result !== y.result
		) {
			return false;
		}
	}
	return true;
}

export const PROMPT_X = 'px-3 sm:px-5 md:px-8';

export function groupRounds(blocks: TranscriptBlock[]): Round[] {
	const rounds: Round[] = [];
	let current: Round | null = null;

	for (const block of blocks) {
		if (block.kind === 'user') {
			if (current) {
				rounds.push(current);
			}
			current = {
				id: `round-${block.message.id}`,
				user: block.message,
				rest: [],
				agentTasks: NO_AGENT_TASKS,
			};
			continue;
		}
		if (!current) {
			current = {
				id: `round-lead-${rounds.length}`,
				rest: [block],
				agentTasks: NO_AGENT_TASKS,
			};
			continue;
		}
		current.rest.push(block);
	}
	if (current) {
		rounds.push(current);
	}
	return rounds;
}

export function restRefsEqual(a: TranscriptBlock[], b: TranscriptBlock[]): boolean {
	if (a.length !== b.length) {
		return false;
	}
	for (let i = 0; i < a.length; i += 1) {
		if (a[i] !== b[i]) {
			return false;
		}
	}
	return true;
}

export function reuseRoundPrefix(prev: Round[] | null, next: Round[]): Round[] {
	if (!prev || prev.length !== next.length) {
		return next;
	}
	let changed = false;
	const out = next.map((round, i) => {
		const old = prev[i]!;
		if (
			old.id === round.id &&
			old.user === round.user &&
			restRefsEqual(old.rest, round.rest)
		) {
			return old;
		}
		changed = true;
		return round;
	});
	return changed ? out : prev;
}
