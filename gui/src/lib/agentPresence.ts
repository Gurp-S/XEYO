/** 从当前对话工具行抽出 agent 在工作区里的落点，供地图高亮。 */

import type {MultiAgentTaskView} from './api';
import {parseJsonValue} from './safeJson';
import type {ChatMessage} from './types';
import {toolToStep} from './toolActivity';

export type AgentPresenceHit = {
	/** 工作区相对路径（posix）。 */
	relPath: string;
	verb: string;
	running: boolean;
	toolName: string;
	createdAt: number;
	/** 主会话为空；子 Agent 带 id。 */
	agentId?: string;
	/** Read.symbol 等符号路径。 */
	symbol?: string;
};

const PATH_KEYS = [
	'file_path',
	'filePath',
	'path',
	'target',
	'target_directory',
	'targetDirectory',
	'notebook_path',
	'notebookPath',
] as const;

function strField(obj: Record<string, unknown> | null, keys: readonly string[]): string {
	if (!obj) {
		return '';
	}
	for (const key of keys) {
		const value = obj[key];
		if (typeof value === 'string' && value.trim()) {
			return value.trim();
		}
	}
	return '';
}

function asRecord(input: unknown): Record<string, unknown> | null {
	const parsed = parseJsonValue<unknown>(input);
	if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
		return parsed as Record<string, unknown>;
	}
	return null;
}

/** 把工具参数里的绝对/相对路径收成工作区相对 posix。 */
export function toWorkspaceRel(path: string, workspaceRoot: string): string {
	const n = path.trim().replace(/\\/g, '/');
	const r = workspaceRoot.trim().replace(/\\/g, '/').replace(/\/+$/, '');
	if (!n) {
		return '';
	}
	if (r) {
		const nl = n.toLowerCase();
		const rl = r.toLowerCase();
		if (nl === rl) {
			return '';
		}
		if (nl.startsWith(`${rl}/`)) {
			return n.slice(r.length).replace(/^\//, '');
		}
	}
	return n.replace(/^\.\//, '');
}

export function collectAgentPresence(
	messages: ChatMessage[],
	workspaceRoot: string,
	tasks?: MultiAgentTaskView[],
): AgentPresenceHit[] {
	const hits: AgentPresenceHit[] = [];
	for (const message of messages) {
		if (message.role !== 'tool' || !message.toolName) {
			continue;
		}
		const obj = asRecord(message.toolInput);
		const raw = strField(obj, PATH_KEYS);
		if (!raw) {
			continue;
		}
		const relPath = toWorkspaceRel(raw, workspaceRoot);
		if (!relPath) {
			continue;
		}
		const status =
			message.toolStatus === 'error'
				? 'error'
				: message.toolStatus === 'done'
					? 'done'
					: 'running';
		const step = toolToStep({
			id: message.id,
			name: message.toolName,
			input: message.toolInput ?? '',
			result: message.text?.startsWith('call ') ? '' : (message.text ?? ''),
			status,
			createdAt: message.createdAt,
		});
		hits.push({
			relPath,
			verb: step.verb,
			running: Boolean(step.running),
			toolName: message.toolName,
			createdAt: message.createdAt,
			...(typeof obj?.symbol === 'string' && obj.symbol.trim()
				? {symbol: obj.symbol.trim()}
				: {}),
		});
	}

	for (const task of tasks ?? []) {
		const running = task.status === 'running' || task.status === 'pending';
		for (const raw of task.filesTouched ?? []) {
			const relPath = toWorkspaceRel(raw, workspaceRoot);
			if (!relPath) {
				continue;
			}
			hits.push({
				relPath,
				verb: running ? 'Delegating' : 'Delegated',
				running,
				toolName: 'Agent',
				createdAt: task.batchAt ?? 0,
				agentId: task.agentId,
			});
		}
	}

	hits.sort((a, b) => a.createdAt - b.createdAt);
	return hits;
}

export function matchHitsToNode(
	hits: AgentPresenceHit[],
	nodeId: string,
	kind: 'file' | 'package',
): AgentPresenceHit[] {
	const id = nodeId.replace(/\\/g, '/').toLowerCase();
	return hits.filter(hit => {
		const path = hit.relPath.replace(/\\/g, '/').toLowerCase();
		if (kind === 'file') {
			return path === id || path.endsWith(`/${id}`) || id.endsWith(`/${path}`);
		}
		return path === id || path.startsWith(`${id}/`);
	});
}

/** 每个节点最近一次命中（进行中优先）。 */
export function latestHitForNode(
	hits: AgentPresenceHit[],
	nodeId: string,
	kind: 'file' | 'package',
): AgentPresenceHit | null {
	const matched = matchHitsToNode(hits, nodeId, kind);
	if (!matched.length) {
		return null;
	}
	const running = matched.filter(h => h.running);
	const pool = running.length ? running : matched;
	return pool[pool.length - 1] ?? null;
}

export type ConversationOp = {
	relPath: string;
	verb: string;
	running: boolean;
	toolName: string;
	createdAt: number;
	agentId?: string;
	symbol?: string;
	/** 同路径累计次数（本轮/会话）。 */
	count: number;
};

/**
 * 把落点压成「对话正在操作哪些路径」清单：按路径去重，进行中优先，最多 limit 条。
 */
export function digestConversationOps(
	hits: AgentPresenceHit[],
	limit = 12,
): ConversationOp[] {
	const byPath = new Map<string, ConversationOp>();
	for (const hit of hits) {
		const key = hit.relPath.replace(/\\/g, '/');
		if (!key) {
			continue;
		}
		const prev = byPath.get(key);
		if (!prev) {
			byPath.set(key, {
				relPath: key,
				verb: hit.verb,
				running: hit.running,
				toolName: hit.toolName,
				createdAt: hit.createdAt,
				count: 1,
				...(hit.agentId ? {agentId: hit.agentId} : {}),
				...(hit.symbol ? {symbol: hit.symbol} : {}),
			});
			continue;
		}
		prev.count += 1;
		const takeNewer =
			hit.running !== prev.running
				? hit.running
				: hit.createdAt >= prev.createdAt;
		if (takeNewer) {
			prev.verb = hit.verb;
			prev.running = hit.running;
			prev.toolName = hit.toolName;
			prev.createdAt = hit.createdAt;
			if (hit.agentId) {
				prev.agentId = hit.agentId;
			}
			if (hit.symbol) {
				prev.symbol = hit.symbol;
			}
		}
	}
	return [...byPath.values()]
		.sort((a, b) => {
			if (a.running !== b.running) {
				return a.running ? -1 : 1;
			}
			return b.createdAt - a.createdAt;
		})
		.slice(0, Math.max(1, limit));
}

/**
 * 本轮落点时间序轨迹（相邻不同路径连边），供地图画主路径。
 * 最多返回 maxEdges 条，避免轨迹把图糊满。
 */
export function buildOpsTrail(
	hits: AgentPresenceHit[],
	maxEdges = 8,
): Array<{from: string; to: string}> {
	const ordered = [...hits].sort((a, b) => a.createdAt - b.createdAt);
	const seq: string[] = [];
	for (const hit of ordered) {
		const p = hit.relPath.replace(/\\/g, '/');
		if (!p) {
			continue;
		}
		if (seq[seq.length - 1] !== p) {
			seq.push(p);
		}
	}
	const edges: Array<{from: string; to: string}> = [];
	for (let i = 1; i < seq.length; i += 1) {
		edges.push({from: seq[i - 1]!, to: seq[i]!});
	}
	return edges.slice(-Math.max(1, maxEdges));
}

export type ReplayFrame = {
	relPath: string;
	verb: string;
	toolName: string;
	createdAt: number;
	running: boolean;
	agentId?: string;
	symbol?: string;
};

/**
 * 按时间序生成回放脚本（不去重：同文件多次读写各自一帧）。
 */
export function buildReplayScript(
	hits: AgentPresenceHit[],
	limit = 40,
): ReplayFrame[] {
	return [...hits]
		.sort((a, b) => a.createdAt - b.createdAt || a.relPath.localeCompare(b.relPath))
		.slice(0, Math.max(1, limit))
		.map(h => ({
			relPath: h.relPath.replace(/\\/g, '/'),
			verb: h.verb,
			toolName: h.toolName,
			createdAt: h.createdAt,
			running: h.running,
			...(h.agentId ? {agentId: h.agentId} : {}),
			...(h.symbol ? {symbol: h.symbol} : {}),
		}))
		.filter(f => Boolean(f.relPath));
}
