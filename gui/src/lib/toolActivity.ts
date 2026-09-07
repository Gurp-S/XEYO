import type {ChatMessage} from './types';
import {parseJsonValue} from './safeJson';
import {type ToolView, type TurnItem} from './groupTranscript';
import {appendLiveThoughtStep, formatThoughtDetail, injectThoughtSteps, normalizeActivitySteps, toolToStep} from './toolActivity/steps';
export {appendLiveThoughtStep, formatThoughtDetail, injectThoughtSteps, normalizeActivitySteps, summarizeTools, toolToStep} from './toolActivity/steps';
export {TODO_LIST_TAG_RE, categorize, collectChangedFiles, collectChangedFilesFromItems, collectLatestTodosFromItems, collectLatestTodosFromSteps, collectLiveSessionTodos, extractDiffFence, isLiveTodoSnapshot, isTodoActivityStep, isTodoToolName, lineRange, mergeChangedFilesWithPaths, normalizeTodoRows, parseTodosFromInput, parseTodosFromResult, todoSnapshotFromTool, writeSettledVerb} from './toolActivity/todos';
export type {TodoItemView, TodoSnapshot, TodoStatus, ToolCat} from './toolActivity/todos';

export type DiffStat = {add: number; del: number};

export type ActivityStep = {
	id: string;
	/** 加粗关键词：Edited / Read / Ran / Grepped … */
	verb: string;
	/** 行内其余部分（文件、模式、命令）。 */
	detail: string;
	/** Thought 步骤的可折叠 reasoning 正文。 */
	thoughtContent?: string;
	/** 原始 tool 参数 JSON（展开 → Args）。 */
	args?: string;
	diff?: DiffStat;
	error?: boolean;
	running?: boolean;
	/** 完整 tool 结果 / stdout（展开 → Output）。 */
	result?: string;
	/** Agent 工具步骤（含 Failed），供卡片挂载识别。 */
	agent?: boolean;
};

export type TurnSegment =
	| {kind: 'prose'; messages: ChatMessage[]}
	| {
			kind: 'activity';
			id: string;
			steps: ActivityStep[];
			summary: string;
			diffs: DiffStat;
	  };

export function basename(path: string): string {
	const norm = path.replace(/\\/g, '/');
	const parts = norm.split('/').filter(Boolean);
	return parts[parts.length - 1] || path;
}

export function parseJson(input: unknown): Record<string, unknown> | null {
	const direct = parseJsonValue<unknown>(input);
	if (direct && typeof direct === 'object' && !Array.isArray(direct)) {
		return direct as Record<string, unknown>;
	}
	if (typeof input !== 'string') {
		return null;
	}
	const t = input.trim();
	if (!t.startsWith('{') && !t.startsWith('[')) {
		return null;
	}
	const v = parseJsonValue(t);
	return v && typeof v === 'object' && !Array.isArray(v)
		? (v as Record<string, unknown>)
		: null;
}

export function strField(
	obj: Record<string, unknown> | null,
	...keys: string[]
): string {
	if (!obj) {
		return '';
	}
	for (const k of keys) {
		const v = obj[k];
		if (typeof v === 'string' && v.trim()) {
			return v.trim();
		}
	}
	return '';
}

export function countDiffHunks(text: string): DiffStat | undefined {
	// 优先 tool_result 中的显式统计："... +12 -3"
	const tagged = text.match(/\+(\d+)\s+-(\d+)/);
	if (tagged) {
		return {add: Number(tagged[1]), del: Number(tagged[2])};
	}
	let add = 0;
	let del = 0;
	for (const line of text.split('\n')) {
		if (line.startsWith('+') && !line.startsWith('+++')) {
			add += 1;
		} else if (line.startsWith('-') && !line.startsWith('---')) {
			del += 1;
		}
	}
	if (add === 0 && del === 0) {
		return undefined;
	}
	return {add, del};
}

/** 当 tool_result 缺少标记统计时的 +/− 回退（Edit/Write 参数）。 */
export function estimateDiffFromArgs(args?: string): DiffStat | undefined {
	const obj = parseJson(args ?? '');
	if (!obj) {
		return undefined;
	}
	if (typeof obj._content_lines === 'number' && obj._content_lines >= 0) {
		return {add: obj._content_lines, del: 0};
	}
	if (typeof obj.content === 'string') {
		const c = obj.content;
		if (!c) {
			return {add: 0, del: 0};
		}
		// 截断的 UI payload："… [N lines, M chars]"
		const meta = c.match(/\[(\d+)\s+lines?/i);
		if (meta) {
			return {add: Number(meta[1]), del: 0};
		}
		return {add: c.split('\n').length, del: 0};
	}
	if (typeof obj.old_string !== 'string' || typeof obj.new_string !== 'string') {
		return undefined;
	}
	const a = obj.old_string === '' ? [] : obj.old_string.split('\n');
	const b = obj.new_string === '' ? [] : obj.new_string.split('\n');
	let add = 0;
	let del = 0;
	const n = Math.max(a.length, b.length);
	for (let i = 0; i < n; i += 1) {
		const left = a[i];
		const right = b[i];
		if (left === undefined) {
			add += 1;
		} else if (right === undefined) {
			del += 1;
		} else if (left !== right) {
			del += 1;
			add += 1;
		}
	}
	if (add === 0 && del === 0) {
		return undefined;
	}
	return {add, del};
}

export type ChangedFile = {
	path: string;
	name: string;
	add: number;
	del: number;
	/** 任意 contributing Write 步骤创建文件时为 true。 */
	created?: boolean;
	/** 统一 diff 正文（无 fence），供展开展示。 */
	diff?: string;
};

export const FILE_CHANGE_VERBS = new Set(['Edited', 'Wrote', 'Created']);

/** 折叠顶栏：done on Aug 28, 2026 · 2:05 PM（段级可选） */
export function formatDoneOn(atMs: number = Date.now()): string {
	const d = new Date(atMs);
	const date = d.toLocaleString('en-US', {
		month: 'short',
		day: 'numeric',
		year: 'numeric',
	});
	const time = d.toLocaleString('en-US', {
		hour: 'numeric',
		minute: '2-digit',
		hour12: true,
	});
	return `done on ${date} · ${time}`;
}

/** 整轮收尾顶栏：done on {timestamp}（冻结口径） */
export function formatCollapsedRoundSummary(
	_durationMs: number,
	endedAt: number = Date.now(),
): string {
	return formatDoneOn(endedAt);
}

/** 折叠段标题：纯 Thought → Thought 4s；否则 N steps（不再用 Explored 汇总）。 */
export function formatCollapsedSegmentLabel(
	steps: ActivityStep[],
	_summary?: string,
): string {
	const nonEmpty = steps.filter(Boolean);
	if (
		nonEmpty.length > 0 &&
		nonEmpty.every(s => s.verb === 'Thought')
	) {
		const detail = nonEmpty[0]?.detail?.trim() || 'briefly';
		return detail === 'briefly' ? 'Thought briefly' : `Thought ${detail}`;
	}
	const n = nonEmpty.filter(s => s.verb !== 'Thought').length || nonEmpty.length;
	if (n <= 0) {
		return 'Done';
	}
	return n === 1 ? '1 step' : `${n} steps`;
}

/**
 * H2：Thought 跳出词命中后续工具 detail → 返回该步骤 id。
 * 优先命中「下一跳」：running，否则 Thought 之后第一条匹配。
 * 针：路径/文件名 + 标识符 + 中文短词（需出现在 detail 内）。
 */
export function findHandoffStepId(
	token: string,
	steps: ActivityStep[],
): string | null {
	const needles = extractHandoffNeedles(token);
	// 无针时仍可用 detail 短名反向命中 Thought 原文
	if (needles.length === 0 && !token.trim()) {
		return null;
	}
	const thoughtIdx = (() => {
		for (let i = steps.length - 1; i >= 0; i -= 1) {
			if (steps[i]?.verb === 'Thought') {
				return i;
			}
		}
		return -1;
	})();
	const score = (step: ActivityStep, index: number): number => {
		if (step.verb === 'Thought' || !step.detail?.trim()) {
			return -1;
		}
		const detail = step.detail.toLowerCase();
		const base = detail.split(/[/\\]/).pop() ?? detail;
		const baseStem = base.replace(/\.[a-z0-9]+$/i, '');
		let hit = false;
		for (const n of needles) {
			if (
				detail.includes(n) ||
				base === n ||
				base.endsWith(n) ||
				step.detail.includes(n)
			) {
				hit = true;
				break;
			}
		}
		// 反向：detail 文件名/中文短名出现在 Thought 原文中
		if (
			!hit &&
			baseStem.length >= 2 &&
			(token.toLowerCase().includes(baseStem) ||
				token.includes(baseStem))
		) {
			hit = true;
		}
		if (!hit) {
			return -1;
		}
		if (step.running) {
			return 3000 + index;
		}
		if (thoughtIdx >= 0 && index > thoughtIdx) {
			return 2000 - (index - thoughtIdx);
		}
		return 1000 - Math.abs(index - Math.max(thoughtIdx, 0));
	};
	let bestId: string | null = null;
	let best = -1;
	for (let i = 0; i < steps.length; i += 1) {
		const s = steps[i]!;
		const sc = score(s, i);
		if (sc > best) {
			best = sc;
			bestId = s.id;
		}
	}
	return bestId;
}

const HANDOFF_PATH_RE =
	/[A-Za-z0-9_.@/-]+\.(?:tsx?|jsx?|mjs|cjs|json|css|scss|md|py|rs|go|html|vue|svelte)\b|[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_.-]+)+/g;

const HANDOFF_IDENT_RE = /[A-Za-z_][A-Za-z0-9_-]{2,}/g;
const HANDOFF_CJK_RE = /[\u4e00-\u9fff]{2,}/g;
const HANDOFF_STOP = new Set([
	'the',
	'and',
	'for',
	'with',
	'from',
	'this',
	'that',
	'into',
	'file',
	'files',
	'read',
	'edit',
	'let',
	'var',
	'const',
	'function',
	'return',
	'true',
	'false',
	'null',
	'undefined',
	'查看',
	'继续',
	'需要',
	'然后',
	'开始',
	'完成',
	'实现',
	'文件',
	'代码',
	'现在',
	'一下',
	'我们',
	'进行',
]);

/** 从 Thought 片段抽出可与工具 detail 对齐的路径/标识符/短词。 */
export function extractHandoffNeedles(token: string): string[] {
	const raw = token.trim();
	if (!raw) {
		return [];
	}
	const found = new Set<string>();
	const lower = raw.toLowerCase();
	for (const m of lower.matchAll(HANDOFF_PATH_RE)) {
		const full = m[0]!;
		found.add(full);
		const base = full.split(/[/\\]/).pop();
		if (base && base !== full) {
			found.add(base);
		}
	}
	if (/^[A-Za-z0-9_.-]+\.(?:tsx?|jsx?|json|css|md|py)$/i.test(raw)) {
		found.add(lower);
	}
	for (const m of lower.matchAll(HANDOFF_IDENT_RE)) {
		const w = m[0]!;
		if (!HANDOFF_STOP.has(w) && w.length >= 3) {
			found.add(w);
		}
	}
	for (const m of raw.matchAll(HANDOFF_CJK_RE)) {
		const w = m[0]!;
		if (!HANDOFF_STOP.has(w) && w.length >= 2) {
			found.add(w);
		}
	}
	return [...found];
}

/** 整轮是否包含工具/thought 等中间过程步骤。 */
export function roundHasIntermediateWork(
	turns: Array<{items: TurnItem[]}>,
): boolean {
	for (const block of turns) {
		for (const item of block.items) {
			if (item.kind === 'tool') {
				return true;
			}
			if (
				item.kind === 'assistant' &&
				item.message.isThought &&
				item.message.text.trim()
			) {
				return true;
			}
		}
	}
	return false;
}

/** 任务收尾后仅保留最终 assistant prose（跳过 isThought 与中间说明）。 */
export function finalRoundProseMessageIds(
	turns: Array<{items: TurnItem[]}>,
): Set<string> {
	let lastId: string | null = null;
	for (const block of turns) {
		for (const item of block.items) {
			if (
				item.kind === 'assistant' &&
				!item.message.isThought &&
				item.message.text.trim()
			) {
				lastId = item.message.id;
			}
		}
	}
	return lastId ? new Set([lastId]) : new Set();
}

/** 收尾展开层：不展示中间 prose/旁白，只保留工具 activity。 */
export function midRoundProseMessageIds(
	_turns: Array<{items: TurnItem[]}>,
): Set<string> {
	return new Set();
}

function estimateTurnDurationMs(turns: Array<{items: TurnItem[]}>): number {
	const startedAt = estimateTurnStartedAt(turns);
	const endedAt = estimateTurnEndedAt(turns);
	if (startedAt == null || endedAt == null) {
		return 0;
	}
	return Math.max(0, endedAt - startedAt);
}

/** 回合内最早事件时间（完成时刻锚点用）。 */
export function estimateTurnStartedAt(
	turns: Array<{items: TurnItem[]}>,
): number | null {
	let min = Infinity;
	for (const block of turns) {
		for (const item of block.items) {
			const t =
				item.kind === 'tool'
					? item.tool.createdAt
					: item.message.createdAt;
			if (typeof t === 'number' && Number.isFinite(t) && t > 0) {
				min = Math.min(min, t);
			}
		}
	}
	return min === Infinity ? null : min;
}

/** 回合内最晚事件时间 = 完成时间（禁止用 Date.now() 冒充）。 */
export function estimateTurnEndedAt(
	turns: Array<{items: TurnItem[]}>,
): number | null {
	let max = 0;
	for (const block of turns) {
		for (const item of block.items) {
			const t =
				item.kind === 'tool'
					? item.tool.createdAt
					: item.message.createdAt;
			if (typeof t === 'number' && Number.isFinite(t) && t > 0) {
				max = Math.max(max, t);
			}
		}
	}
	return max > 0 ? max : null;
}

/**
 * 任务收尾聚合：把一个 submit 内多个 turn 的工具步骤合并成
 * 单个可展开层的数据（MessageList 在"最后一轮为纯文本回复且已 settle"
 * 时调用）。无任何工具步骤时返回 null。
 */
export function mergeTurnActivity(
	turns: Array<{items: TurnItem[]}>,
	opts?: {startedAt?: number; endedAt?: number},
): {steps: ActivityStep[]; summary: string; diffs: DiffStat} | null {
	const steps: ActivityStep[] = [];
	for (const block of turns) {
		for (const seg of segmentTurn(block.items)) {
			if (seg.kind === 'activity') {
				steps.push(...seg.steps);
			}
		}
	}
	if (steps.length === 0) {
		return null;
	}
	const startedAt = opts?.startedAt ?? estimateTurnStartedAt(turns) ?? undefined;
	const endedAt =
		opts?.endedAt ?? estimateTurnEndedAt(turns) ?? Date.now();
	const durationMs =
		startedAt != null && endedAt > startedAt
			? endedAt - startedAt
			: estimateTurnDurationMs(turns);
	const {diffs} = aggregateSteps(steps);
	return {
		steps,
		summary: formatCollapsedRoundSummary(durationMs, endedAt),
		diffs,
	};
}

export type RoundActivityView = {
	steps: ActivityStep[];
	summary: string;
	diffs: DiffStat;
	active: boolean;
};

/**
 * 整轮 submit 的 activity 汇总：合并所有 turn 的工具/思考步骤。
 * - 进行中：展开 + aggregate 摘要
 * - 纯文本收尾：折叠 + worked for
 */
export function buildRoundActivityView(
	turns: Array<{items: TurnItem[]}>,
	opts: {
		startedAt?: number;
		endedAt?: number;
		taskFinalAnswerDone: boolean;
		roundLive: boolean;
		liveThought?: {since: number; content?: string};
	},
): RoundActivityView | null {
	const merged = mergeTurnActivity(turns, {
		startedAt: opts.startedAt,
		endedAt: opts.endedAt,
	});
	let steps = merged?.steps ?? [];

	const toolRunning = steps.some(s => s.running && s.verb !== 'Thought');
	if (opts.roundLive && opts.liveThought && !toolRunning) {
		const streamThoughtIdx = steps.findLastIndex(s => s.verb === 'Thought');
		if (streamThoughtIdx >= 0) {
			const elapsed = (opts.liveThought.since != null
				? Date.now() - opts.liveThought.since
				: 0);
			steps = steps.map((s, i) =>
				i === streamThoughtIdx
					? {
							...s,
							detail: formatThoughtDetail(elapsed),
							thoughtContent: opts.liveThought!.content?.trim() || s.thoughtContent,
							running: true,
						}
					: s,
			);
		} else {
			steps = appendLiveThoughtStep(steps, {
				active: true,
				since: opts.liveThought.since,
				content: opts.liveThought.content,
			});
		}
	}

	if (steps.length === 0) {
		return null;
	}

	steps = normalizeActivitySteps(steps, opts.roundLive);

	if (opts.taskFinalAnswerDone) {
		const startedAt =
			opts.startedAt ?? estimateTurnStartedAt(turns) ?? undefined;
		const endedAt =
			opts.endedAt ?? estimateTurnEndedAt(turns) ?? Date.now();
		const durationMs =
			startedAt != null && endedAt > startedAt
				? endedAt - startedAt
				: estimateTurnDurationMs(turns);
		const {diffs} = aggregateSteps(steps);
		return {
			steps,
			summary: formatCollapsedRoundSummary(durationMs, endedAt),
			diffs,
			active: false,
		};
	}

	const {summary, diffs} = aggregateSteps(steps);
	return {steps, summary, diffs, active: opts.roundLive};
}

/** Verb → 汇总类别（与 summarizeTools 的 categorize 语义对齐）。 */
function stepCategory(
	step: ActivityStep,
): 'write' | 'edit' | 'read' | 'search' | 'run' | 'todo' | 'lint' | 'thought' {
	const v = step.verb;
	if (v === 'Thought') {
		return 'thought';
	}
	if (
		v === 'Grepping' ||
		v === 'Grepped' ||
		v === 'Globbing' ||
		v === 'Globbed' ||
		v === 'Searching' ||
		v === 'Searched'
	) {
		return 'search';
	}
	if (v === 'Reading' || v === 'Read' || v === 'Capturing' || v === 'Captured') {
		return 'read';
	}
	if (v === 'Writing' || v === 'Wrote' || v === 'Created' || v === 'Creating') {
		return 'write';
	}
	if (v === 'Editing' || v === 'Edited' || v === 'Failed') {
		return 'edit';
	}
	if (v === 'Linting' || v === 'Linted' || v === 'Diagnostics') {
		return 'lint';
	}
	if (v === 'Updating' || v === 'Checked') {
		return 'todo';
	}
	return 'run';
}

/**
 * 工具汇总：Edited N files, explored M files, K searches, lints, ran C commands
 * 后续项小写；+diff 由调用方着色，不拼进 label。
 */
export function formatCursorToolParts(steps: ActivityStep[]): {
	parts: string[];
	diffs: DiffStat;
} {
	let created = 0;
	let wrote = 0;
	let edited = 0;
	let read = 0;
	let searches = 0;
	let commands = 0;
	let todos = 0;
	let lints = 0;
	let add = 0;
	let del = 0;
	const seen = new Set<string>();
	for (const step of steps) {
		if (step.diff) {
			add += step.diff.add;
			del += step.diff.del;
		}
		const key = `${stepCategory(step)}:${step.detail || step.id}`;
		if (seen.has(key)) {
			continue;
		}
		seen.add(key);
		switch (stepCategory(step)) {
			case 'write':
				if (step.verb === 'Created' || step.verb === 'Creating') {
					created += 1;
				} else {
					wrote += 1;
				}
				break;
			case 'edit':
				edited += 1;
				break;
			case 'read':
				read += 1;
				break;
			case 'search':
				searches += 1;
				break;
			case 'todo':
				todos += 1;
				break;
			case 'lint':
				lints += 1;
				break;
			case 'thought':
				break;
			default:
				commands += 1;
		}
	}

	const raw: string[] = [];
	if (created > 0) {
		raw.push(`Created ${created} file${created === 1 ? '' : 's'}`);
	}
	if (wrote > 0) {
		raw.push(`Wrote ${wrote} file${wrote === 1 ? '' : 's'}`);
	}
	if (edited > 0) {
		raw.push(`Edited ${edited} file${edited === 1 ? '' : 's'}`);
	}
	if (read > 0) {
		raw.push(`Read ${read} file${read === 1 ? '' : 's'}`);
	}
	if (searches > 0) {
		raw.push(`${searches} search${searches === 1 ? '' : 'es'}`);
	}
	if (lints > 0) {
		raw.push('lints');
	}
	if (commands > 0) {
		raw.push(`ran ${commands} command${commands === 1 ? '' : 's'}`);
	}
	if (todos > 0) {
		raw.push('updated to-dos');
	}
	if (raw.length === 0 && steps.some(s => s.verb !== 'Thought')) {
		const n = steps.filter(s => s.verb !== 'Thought').length;
		raw.push(`Ran ${n} tool${n === 1 ? '' : 's'}`);
	}
	// 首项保持大写，后续项首字母小写（Edited …, explored …）
	const parts = raw.map((p, i) =>
		i === 0 ? p : p.replace(/^[A-Z]/, c => c.toLowerCase()),
	);
	return {parts, diffs: {add, del}};
}

/**
 * 把多轮的 ActivityStep 聚合成一条总摘要（任务收尾后的单层折叠用）。
 * 计数语义与 summarizeTools 一致：文件类按 detail 去重。
 */
export function aggregateSteps(steps: ActivityStep[]): {
	summary: string;
	diffs: DiffStat;
} {
	const {parts, diffs} = formatCursorToolParts(steps);
	let summary = parts.join(', ');
	if (diffs.add > 0 || diffs.del > 0) {
		summary = summary
			? `${summary} +${diffs.add} -${diffs.del}`
			: `+${diffs.add} -${diffs.del}`;
	}
	if (!summary) {
		summary = 'Working…';
	}
	return {summary, diffs};
}

/**
 * 将一轮拆分为 prose 与 activity 段，按 transcript 顺序交错排列。
 */
export function segmentTurn(items: TurnItem[]): TurnSegment[] {
	const segments: TurnSegment[] = [];
	const activitySteps: ActivityStep[] = [];
	let toolBatch: ToolView[] = [];
	const hasPersistedThoughts = items.some(
		item =>
			item.kind === 'assistant' &&
			item.message.isThought &&
			item.message.text.trim(),
	);

	const flushToolsIntoActivity = () => {
		if (toolBatch.length === 0) {
			return;
		}
		const toolSteps = toolBatch.map(toolToStep);
		activitySteps.push(
			...(hasPersistedThoughts
				? toolSteps
				: injectThoughtSteps(toolSteps, toolBatch)),
		);
		toolBatch = [];
	};

	const emitActivity = () => {
		flushToolsIntoActivity();
		if (activitySteps.length === 0) {
			return;
		}
		const {summary, diffs} = aggregateSteps(activitySteps);
		segments.push({
			kind: 'activity',
			id: `act-${segments.length}`,
			steps: [...activitySteps],
			summary,
			diffs,
		});
		activitySteps.length = 0;
	};

	for (const item of items) {
		if (item.kind === 'tool') {
			toolBatch.push(item.tool);
			continue;
		}
		const m = item.message;
		if (m.isThought && m.text.trim()) {
			flushToolsIntoActivity();
			activitySteps.push({
				id: m.id,
				verb: 'Thought',
				detail: formatThoughtDetail(m.thoughtMs ?? 0),
				thoughtContent: m.text.trim(),
				running: false,
			});
			continue;
		}
		emitActivity();
		if (m.reasoningBefore?.trim()) {
			const thoughtStep: ActivityStep = {
				id: `thought-before-${m.id}`,
				verb: 'Thought',
				detail: formatThoughtDetail(m.thoughtMs ?? 0),
				thoughtContent: m.reasoningBefore.trim(),
				running: false,
			};
			const {summary, diffs} = aggregateSteps([thoughtStep]);
			segments.push({
				kind: 'activity',
				id: `act-${segments.length}`,
				steps: [thoughtStep],
				summary,
				diffs,
			});
		}
		segments.push({kind: 'prose', messages: [m]});
	}
	emitActivity();
	return segments;
}
