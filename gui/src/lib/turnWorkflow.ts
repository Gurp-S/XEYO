/** 从当前对话最近一轮抽出工具步骤，供「本轮」泳道工作流。 */

import {TURN_STEP_CAP, fitLabel} from './codeMapLayout';
import {groupTranscript, latestUserTurnBoundary} from './groupTranscript';
import {parseJsonValue} from './safeJson';
import {toolToStep, type ActivityStep} from './toolActivity';
import type {ChatMessage} from './types';

export type TurnWorkflowLane =
	| 'agent'
	| 'read'
	| 'write'
	| 'search'
	| 'command'
	| 'other'
	| 'files';

export type TurnWorkflowStep = {
	id: string;
	lane: Exclude<TurnWorkflowLane, 'files'>;
	verb: string;
	detail: string;
	running: boolean;
	waiting: boolean;
	error: boolean;
	relPath?: string;
	toolName: string;
	createdAt: number;
};

function laneOf(
	step: ActivityStep,
	toolName: string,
): Exclude<TurnWorkflowLane, 'files'> {
	if (step.agent || toolName.toLowerCase() === 'agent') {
		return 'agent';
	}
	const v = step.verb.toLowerCase();
	const n = toolName.toLowerCase();
	if (v.includes('read') || v.includes('captur') || n === 'read') {
		return 'read';
	}
	if (
		v.includes('edit') ||
		v.includes('writ') ||
		v.includes('creat') ||
		n === 'edit' ||
		n === 'write' ||
		n === 'notebookedit'
	) {
		return 'write';
	}
	if (
		v.includes('grep') ||
		v.includes('glob') ||
		v.includes('search') ||
		n.includes('grep') ||
		n.includes('glob') ||
		n.includes('search')
	) {
		return 'search';
	}
	if (v.includes('ran') || v.includes('run') || n === 'bash' || n === 'git') {
		return 'command';
	}
	return 'other';
}

function pathFromInput(input: string | undefined): string | undefined {
	const parsed = parseJsonValue<unknown>(input);
	if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
		return undefined;
	}
	const obj = parsed as Record<string, unknown>;
	for (const key of [
		'file_path',
		'filePath',
		'path',
		'target',
		'target_directory',
		'targetDirectory',
		'notebook_path',
		'notebookPath',
	]) {
		const v = obj[key];
		if (typeof v === 'string' && v.trim()) {
			return v.trim().replace(/\\/g, '/');
		}
	}
	return undefined;
}

/** 取最近一轮的工具步骤，复用 transcript 对旧 call/result 配对与孤儿状态的归一化。 */
export function buildTurnWorkflow(
	messages: ChatMessage[],
	streamLive = true,
): TurnWorkflowStep[] {
	if (!messages.length) {
		return [];
	}
	const boundary = latestUserTurnBoundary(messages);
	if (!boundary) {
		return [];
	}
	const steps: TurnWorkflowStep[] = [];
	const turnItems = groupTranscript(messages.slice(boundary.index), {
		isLoading: streamLive,
	}).flatMap(block => (block.kind === 'turn' ? block.items : []));
	for (const item of turnItems) {
		if (item.kind !== 'tool') {
			continue;
		}
		const tool = item.tool;
		const step = toolToStep(tool);
		const waiting = Boolean(tool.waiting);
		steps.push({
			id: tool.id,
			lane: laneOf(step, tool.name),
			verb: step.verb,
			detail: step.detail,
			running: Boolean(step.running && !waiting),
			waiting,
			error: tool.status === 'error' || Boolean(step.error),
			relPath: pathFromInput(tool.input),
			toolName: tool.name,
			createdAt: tool.createdAt,
		});
	}
	return steps;
}

/** 把本轮步骤排成泳道，并追加一行「动过的文件」节点。 */
export function turnWorkflowToLanes(
	steps: TurnWorkflowStep[],
	touchedPaths: string[] = [],
): {
	items: Array<{
		id: string;
		name: string;
		layer: string;
		files?: number;
		kind?: 'step' | 'file';
	}>;
	edges: Array<{from: string; to: string}>;
	stepById: Map<string, TurnWorkflowStep>;
} {
	const capped =
		steps.length > TURN_STEP_CAP
			? steps.slice(steps.length - TURN_STEP_CAP)
			: steps;
	const stepById = new Map(capped.map(s => [s.id, s]));
	const items: Array<{
		id: string;
		name: string;
		layer: string;
		kind?: 'step' | 'file';
	}> = capped.map(s => ({
		id: s.id,
		name: fitLabel(s.detail || s.verb || s.toolName, 18),
		layer: s.lane,
		kind: 'step' as const,
	}));
	const edges: Array<{from: string; to: string}> = [];
	for (let i = 0; i < capped.length - 1; i++) {
		edges.push({from: capped[i]!.id, to: capped[i + 1]!.id});
	}

	const seen = new Set<string>();
	const fileIds: string[] = [];
	for (const raw of touchedPaths) {
		const path = raw.replace(/\\/g, '/').replace(/^\.\//, '');
		if (!path || seen.has(path)) {
			continue;
		}
		seen.add(path);
		fileIds.push(path);
		if (fileIds.length >= TURN_STEP_CAP) {
			break;
		}
	}
	for (const path of fileIds) {
		const base = path.split('/').pop() || path;
		items.push({
			id: path,
			name: fitLabel(base, 18),
			layer: 'files',
			kind: 'file',
		});
	}
	for (let i = 0; i < fileIds.length - 1; i++) {
		edges.push({from: fileIds[i]!, to: fileIds[i + 1]!});
	}
	return {items, edges, stepById};
}
