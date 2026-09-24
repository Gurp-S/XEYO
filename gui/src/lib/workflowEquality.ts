import type {MultiAgentTaskView} from './api/core';
import type {ActivityStep} from './toolActivity';

function stringArraysEqual(a: string[] | undefined, b: string[] | undefined): boolean {
	if (a === b) return true;
	if (!a || !b || a.length !== b.length) return false;
	for (let i = 0; i < a.length; i += 1) {
		if (a[i] !== b[i]) return false;
	}
	return true;
}

/** 比较子 Agent 卡片、轮次归属和 Changes 汇总依赖的全部字段。 */
export function multiAgentTaskViewsEqual(
	a: readonly MultiAgentTaskView[] | undefined,
	b: readonly MultiAgentTaskView[] | undefined,
): boolean {
	if (a === b) return true;
	if (!a || !b || a.length !== b.length) return false;
	for (let i = 0; i < a.length; i += 1) {
		const x = a[i]!;
		const y = b[i]!;
		if (
			x.uid !== y.uid ||
			x.taskId !== y.taskId ||
			x.agentId !== y.agentId ||
			x.desc !== y.desc ||
			x.status !== y.status ||
			x.cancelRequested !== y.cancelRequested ||
			x.reason !== y.reason ||
			x.result !== y.result ||
			x.readOnly !== y.readOnly ||
			!stringArraysEqual(x.scope, y.scope) ||
			!stringArraysEqual(x.filesTouched, y.filesTouched) ||
			x.turnId !== y.turnId ||
			x.batchAt !== y.batchAt ||
			x.inboxCount !== y.inboxCount ||
			x.tokensUsed !== y.tokensUsed ||
			x.costCny !== y.costCny
		) {
			return false;
		}
	}
	return true;
}

/** ActivityStep 的完整展示值比较，避免同长度的流式结果被旧行吞掉。 */
export function activityStepEqual(a: ActivityStep, b: ActivityStep): boolean {
	return (
		a.id === b.id &&
		a.toolUseId === b.toolUseId &&
		a.verb === b.verb &&
		a.detail === b.detail &&
		a.thoughtContent === b.thoughtContent &&
		a.args === b.args &&
		a.result === b.result &&
		a.error === b.error &&
		a.running === b.running &&
		a.waiting === b.waiting &&
		a.agent === b.agent &&
		a.diff?.add === b.diff?.add &&
		a.diff?.del === b.diff?.del
	);
}

export function activityStepsEqual(
	a: readonly ActivityStep[],
	b: readonly ActivityStep[],
): boolean {
	if (a === b) return true;
	if (a.length !== b.length) return false;
	for (let i = 0; i < a.length; i += 1) {
		if (!activityStepEqual(a[i]!, b[i]!)) return false;
	}
	return true;
}
