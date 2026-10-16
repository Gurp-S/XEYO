import type {MultiAgentTaskView, SessionAgentMeta} from '@/lib/api';

const reads = new WeakMap<object, Map<string, symbol>>();
export function beginAgentListRead(owner: object, sid: string) {
	let pending = reads.get(owner);
	if (!pending) { pending = new Map(); reads.set(owner, pending); }
	const token = Symbol();
	pending.set(sid, token);
	return token;
}
export function agentListReadCurrent(owner: object, sid: string, token: symbol) {
	return reads.get(owner)?.get(sid) === token;
}
export function invalidateAgentListRead(owner: object, sid: string) {
	reads.get(owner)?.delete(sid);
}

/** Durable attempts replace the matching card, including completed backgrounds. */
export function projectManagedAgents(existing: MultiAgentTaskView[], metas: SessionAgentMeta[]) {
	let tasks = [...existing];
	for (const meta of metas) {
		if (!meta.attemptId) continue;
		const old = tasks.find(task => task.agentId === meta.agentId);
		if (old?.runtimeUpdatedAt && meta.updatedAt && old.runtimeUpdatedAt > meta.updatedAt) continue;
		const sameAttempt = !old?.attemptId || old.attemptId === meta.attemptId;
		const task: MultiAgentTaskView = {
			...old, uid: old?.uid ?? meta.agentId, taskId: meta.taskId, agentId: meta.agentId,
			desc: meta.desc, attemptId: meta.attemptId, runtimeUpdatedAt: meta.updatedAt,
			status: meta.status === 'running' ? 'running' : meta.status === 'done' ? 'done' : 'failed',
			result: meta.resultPreview, reason: meta.status === 'failed' ? meta.runtimeState : undefined,
			batchAt: sameAttempt ? old?.batchAt ?? meta.startedAt : meta.startedAt,
			cancelRequested: meta.status === 'running' && sameAttempt ? old?.cancelRequested : false,
			readOnly: meta.readOnly, scope: meta.scope, inboxCount: meta.inboxCount ?? 0,
			tokensUsed: meta.tokensUsed, costCny: meta.costCny, costPartial: meta.costPartial,
		};
		tasks = tasks.filter(value => value.agentId !== meta.agentId);
		tasks.push(task);
	}
	return tasks;
}
