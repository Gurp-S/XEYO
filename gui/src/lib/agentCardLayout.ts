/**
 * 子 Agent 卡片挂载：连续 Agent 步骤 = 并发成组；
 * 被 Thought / 其它工具打断 = 串行，逐步旁挂卡。
 *
 * 不把「尚未出现步骤的 pending 任务」堆到已有步骤上（否则串行第一步会冒出多张卡）。
 */

export type AgentCardMount = {
	/** 卡片挂在该步骤之后 */
	afterStepIndex: number;
	/** inlineAgentTasks 切片起（含） */
	taskStart: number;
	/** inlineAgentTasks 切片止（不含） */
	taskEnd: number;
};

export function isAgentActivityStep(step: {
	verb: string;
	agent?: boolean;
}): boolean {
	if (step.agent) {
		return true;
	}
	return step.verb === 'Delegating' || step.verb === 'Delegated';
}

export function countAgentActivitySteps(
	steps: ReadonlyArray<{verb: string; agent?: boolean}>,
): number {
	let n = 0;
	for (const s of steps) {
		if (isAgentActivityStep(s)) {
			n += 1;
		}
	}
	return n;
}

/**
 * 规划卡片挂载点（本段 activity 内）。
 *
 * - 并发：`[D,D,D]` → 三张卡都在最后一条 D 后
 * - 串行：`[D, Thought, Failed]` → 各 Agent 步骤后挂对应卡
 * - 任务数与步骤一对一；多出的 pending 不挂（等对应 Delegating 出现）
 */
export function planAgentCardMounts(
	steps: ReadonlyArray<{verb: string; agent?: boolean}>,
	taskCount: number,
): AgentCardMount[] {
	if (taskCount <= 0 || steps.length === 0) {
		return [];
	}
	const agentIdx: number[] = [];
	for (let i = 0; i < steps.length; i += 1) {
		if (isAgentActivityStep(steps[i]!)) {
			agentIdx.push(i);
		}
	}
	if (agentIdx.length === 0) {
		return [];
	}

	const mounts: AgentCardMount[] = [];
	let runOrdStart = 0;
	for (let k = 0; k < agentIdx.length; k += 1) {
		const stepI = agentIdx[k]!;
		const next = agentIdx[k + 1];
		const runEnds = next == null || next !== stepI + 1;
		if (!runEnds) {
			continue;
		}
		const taskStart = runOrdStart;
		const taskEnd = k + 1;
		const start = Math.min(taskStart, taskCount);
		const end = Math.min(Math.max(taskEnd, start), taskCount);
		if (end > start) {
			mounts.push({
				afterStepIndex: stepI,
				taskStart: start,
				taskEnd: end,
			});
		}
		runOrdStart = k + 1;
	}
	return mounts;
}
