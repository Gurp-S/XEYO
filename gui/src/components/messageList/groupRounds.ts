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
import {multiAgentTaskViewsEqual} from '@/lib/workflowEquality';
import {parseJsonValue} from '@/lib/safeJson';

export const NO_AGENT_TASKS: MultiAgentTaskView[] = [];

/**
 * 多 Agent 卡片 → 轮次锚定：任务落在「触发它的那条用户
 * 消息」所在轮。优先用 Agent 工具调用里的 task_id 精确锚定；旧记录缺少
 * 调用身份时才按 batchAt / meta.startedAt 时间回退，避免同毫秒边界串轮。
 * 无锚点（异常）时兜底挂最早一轮。
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
	const roundsByTaskId = new Map<string, number[]>();
	for (let index = 0; index < rounds.length; index += 1) {
		for (const block of rounds[index]!.rest) {
			if (block.kind !== 'turn') continue;
			for (const item of block.items) {
				if (
					item.kind !== 'tool' ||
					(item.tool.name !== 'Agent' && item.tool.name !== 'Task')
				) {
					continue;
				}
				const input = parseJsonValue<Record<string, unknown>>(item.tool.input);
				const taskId = String(input?.task_id ?? input?.taskId ?? '').trim();
				if (taskId) {
					const matches = roundsByTaskId.get(taskId) ?? [];
					if (matches[matches.length - 1] !== index) {
						matches.push(index);
					}
					roundsByTaskId.set(taskId, matches);
				}
			}
		}
	}
	// SSE 按批次序到达 / 后端 meta 按 startedAt 升序，这里排序仅为兜底乱序。
	const ordered =
		tasks.length > 1
			? [...tasks].sort(
					(a, b) =>
						(normalizedBatchAt(a.batchAt) ?? Number.NEGATIVE_INFINITY) -
						(normalizedBatchAt(b.batchAt) ?? Number.NEGATIVE_INFINITY),
				)
			: tasks;
	let cursor = 0;
	for (const task of ordered) {
		const at = normalizedBatchAt(task.batchAt);
		const exactRounds = roundsByTaskId.get(task.taskId.trim()) ?? [];
		let exactIndex: number | undefined;
		if (exactRounds.length === 1) {
			exactIndex = exactRounds[0];
		} else if (exactRounds.length > 1 && at != null) {
			// 后端兜底任务会跨批次重复使用 t1/t2 等 ID；按批次时间
			// 定位重复 ID，选择启动时刻之前最近的一条用户轮。
			const timestamped = exactRounds
				.map(index => ({index, createdAt: rounds[index]!.user?.createdAt}))
				.filter(
					(candidate): candidate is {index: number; createdAt: number} =>
						typeof candidate.createdAt === 'number' &&
						Number.isFinite(candidate.createdAt),
				);
			const preceding = timestamped.filter(candidate => candidate.createdAt <= at);
			if (preceding.length > 0) {
				exactIndex = preceding.reduce((best, candidate) =>
					candidate.createdAt > best.createdAt ||
					(candidate.createdAt === best.createdAt && candidate.index > best.index)
						? candidate
						: best,
				).index;
			} else if (timestamped.length > 0) {
				exactIndex = timestamped.reduce((best, candidate) =>
					candidate.createdAt < best.createdAt ||
					(candidate.createdAt === best.createdAt && candidate.index < best.index)
						? candidate
						: best,
				).index;
			} else {
				exactIndex = exactRounds[0];
			}
		} else if (exactRounds.length > 1) {
			exactIndex = exactRounds.find(index => index >= cursor) ?? exactRounds[0];
		}
		if (exactIndex == null && at != null) {
			while (
				cursor + 1 < rounds.length &&
				rounds[cursor + 1]!.user !== undefined &&
				(rounds[cursor + 1]!.user?.createdAt ?? Number.MAX_SAFE_INTEGER) <= at
			) {
				cursor += 1;
			}
		}
		let idx = exactIndex ?? cursor;
		cursor = Math.max(cursor, idx);
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
		if (multiAgentTaskViewsEqual(round.agentTasks, next)) {
			return round;
		}
		return {...round, agentTasks: next};
	});
}

/** 任务列表浅比较；覆盖 Agent 卡片展示的所有可变字段。 */
export function agentTasksSame(
	a: MultiAgentTaskView[],
	b: MultiAgentTaskView[],
): boolean {
	return multiAgentTaskViewsEqual(a, b);
}

function normalizedBatchAt(value: number | undefined): number | null {
	return value != null && Number.isFinite(value) ? value : null;
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
