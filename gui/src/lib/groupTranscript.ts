import type {ChatMessage} from './types';

export type ToolView = {
	id: string;
	name: string;
	input: string;
	result: string;
	status: 'running' | 'done' | 'error';
	createdAt: number;
	reasoningBefore?: string;
	thoughtMs?: number;
};

export type TurnItem =
	| {kind: 'assistant'; message: ChatMessage}
	| {kind: 'tool'; tool: ToolView};

export type TranscriptBlock =
	| {kind: 'user'; message: ChatMessage}
	| {kind: 'system'; message: ChatMessage}
	| {
			kind: 'turn';
			id: string;
			items: TurnItem[];
			streaming?: string;
			thinking?: string;
			/** 为 true 时表示 transcript 的实时尾部。 */
			active: boolean;
	  };

function isToolCall(m: ChatMessage): boolean {
	if (m.role !== 'tool') {
		return false;
	}
	if (m.toolStatus === 'running' || m.toolStatus === 'waiting') {
		return true;
	}
	if (m.toolInput !== undefined) {
		return m.toolStatus !== 'done' && m.toolStatus !== 'error';
	}
	return m.text.startsWith('call ');
}

function toolInputOf(m: ChatMessage): string {
	if (m.toolInput !== undefined) {
		return m.toolInput;
	}
	if (m.text.startsWith('call ')) {
		return m.text.slice(5);
	}
	return '';
}

function toolResultOf(m: ChatMessage): string {
	if (m.text.startsWith('call ')) {
		return '';
	}
	// 即使 status 滞后于 'running' 也保留 payload — UI 必须能 settle。
	return m.text;
}

function toolStatusOf(m: ChatMessage): ToolView['status'] {
	const body = m.text.startsWith('call ') ? '' : m.text.trim();
	// 结果已到达 → 永不视为仍在 running（避免 shimmer 卡住）。
	if (
		(m.toolStatus === 'running' || m.toolStatus === 'waiting') &&
		body
	) {
		return body.startsWith('[error]') ? 'error' : 'done';
	}
	// 流已结束、仍等晚到 tool_result：UI 继续当 running 展示。
	if (m.toolStatus === 'waiting') {
		return 'running';
	}
	if (m.toolStatus) {
		return m.toolStatus;
	}
	if (m.text.startsWith('call ')) {
		return 'running';
	}
	return m.text.startsWith('[error]') ? 'error' : 'done';
}

function toToolView(m: ChatMessage): ToolView {
	return {
		id: m.id,
		name: m.toolName ?? 'tool',
		input: toolInputOf(m),
		result: toolResultOf(m),
		status: toolStatusOf(m),
		createdAt: m.createdAt,
		reasoningBefore: m.reasoningBefore,
		thoughtMs: m.thoughtMs,
	};
}

/**
 * 配对旧版分离的 call/result 行；现代消息已合并为单行。
 */
function consumeTools(
	messages: ChatMessage[],
	start: number,
): {item: TurnItem; next: number} | null {
	const m = messages[start];
	if (!m || m.role !== 'tool') {
		return null;
	}

	// 现代就地 tool 行（含 toolInput 或 toolStatus）。
	if (m.toolInput !== undefined || m.toolStatus !== undefined) {
		return {item: {kind: 'tool', tool: toToolView(m)}, next: start + 1};
	}

	if (isToolCall(m)) {
		const call = toToolView(m);
		const nextMsg = messages[start + 1];
		if (
			nextMsg?.role === 'tool' &&
			!isToolCall(nextMsg) &&
			(nextMsg.toolName ?? 'tool') === call.name
		) {
			return {
				item: {
					kind: 'tool',
					tool: {
						...call,
						id: call.id,
						result: toolResultOf(nextMsg),
						status: toolStatusOf(nextMsg),
					},
				},
				next: start + 2,
			};
		}
		return {item: {kind: 'tool', tool: call}, next: start + 1};
	}

	// 孤立的旧版 result
	return {item: {kind: 'tool', tool: toToolView(m)}, next: start + 1};
}

/** 清除历史轮次上卡住的 running shimmer（流结束后清除所有轮次）。 */
function settleOrphanRunningInBlocks(
	blocks: TranscriptBlock[],
	streamLive: boolean,
): void {
	for (const b of blocks) {
		if (b.kind !== 'turn') {
			continue;
		}
		// 流式期间仅重写已完成的历史轮次 — 不碰实时尾部。
		if (streamLive && b.active) {
			continue;
		}
		for (let i = 0; i < b.items.length; i += 1) {
			const item = b.items[i];
			if (item?.kind !== 'tool') {
				continue;
			}
			if (item.tool.status === 'running' && !item.tool.result.trim()) {
				b.items[i] = {
					kind: 'tool',
					tool: {...item.tool, status: 'error'},
				};
			}
		}
	}
}

/** 将扁平聊天消息分组为 user / system / assistant-turn 块。 */
export function groupTranscript(
	messages: ChatMessage[],
	opts?: {
		streamingText?: string;
		isLoading?: boolean;
		statusText?: string;
		reasoningText?: string;
	},
): TranscriptBlock[] {
	const blocks: TranscriptBlock[] = [];
	let i = 0;
	let turnSeq = 0;

	const pushTurn = (
		items: TurnItem[],
		extra?: {streaming?: string; thinking?: string; active?: boolean},
	) => {
		if (
			items.length === 0 &&
			!extra?.streaming &&
			!extra?.thinking
		) {
			return;
		}
		blocks.push({
			kind: 'turn',
			id: `turn-${turnSeq++}`,
			items,
			streaming: extra?.streaming,
			thinking: extra?.thinking,
			active: Boolean(extra?.active),
		});
	};

	while (i < messages.length) {
		const m = messages[i]!;
		if (m.role === 'user') {
			blocks.push({kind: 'user', message: m});
			i += 1;
			continue;
		}
		if (m.role === 'system') {
			blocks.push({kind: 'system', message: m});
			i += 1;
			continue;
		}

		const items: TurnItem[] = [];
		while (i < messages.length) {
			const cur = messages[i]!;
			if (cur.role === 'user' || cur.role === 'system') {
				break;
			}
			if (cur.role === 'assistant') {
				items.push({kind: 'assistant', message: cur});
				i += 1;
				continue;
			}
			const consumed = consumeTools(messages, i);
			if (!consumed) {
				i += 1;
				continue;
			}
			items.push(consumed.item);
			i = consumed.next;
		}
		pushTurn(items);
	}

	const streaming = opts?.streamingText?.trim()
		? opts.streamingText
		: undefined;
	const thinking =
		opts?.isLoading && opts?.reasoningText?.trim()
			? opts.reasoningText.trim()
			: undefined;

	if (streaming || thinking) {
		const last = blocks[blocks.length - 1];
		if (last?.kind === 'turn') {
			last.streaming = streaming;
			last.thinking = thinking;
			last.active = true;
			const stripped = stripDrainDuplicateProse(last, streaming);
			if (stripped !== last) {
				blocks[blocks.length - 1] = stripped;
			}
		} else {
			pushTurn([], {streaming, thinking, active: true});
		}
	} else if (opts?.isLoading) {
		// 在 tool 批次之间 / 最终 prose 之前保持 live turn 活跃，
		// 以便 Files Changed 等 UI 等到整轮回复 settle。
		const last = blocks[blocks.length - 1];
		if (last?.kind === 'turn') {
			last.active = true;
		}
	}

	settleOrphanRunningInBlocks(blocks, Boolean(opts?.isLoading));
	return blocks;
}

/**
 * drain 路径会先把全文写入 messages，再靠 streamingShown 打字机追赶。
 * 若同时渲染已落盘 prose + StreamingBody，多 Agent 批末突发摘要会整段「闪现」。
 * 仅当 turn 末项就是该 assistant（drain 预写入）且 streaming 为其前缀时隐藏。
 *
 * 与 appendAssistantProse 的 trim 对齐：比较时对 streaming 做 trimEnd，
 * 避免 committed="hello" / streaming="hello\n" 去重失败导致双份正文。
 */
function stripDrainDuplicateProse<T extends {kind: string; items?: TurnItem[]}>(
	turn: T,
	streaming: string | undefined,
): T {
	if (!streaming || turn.kind !== 'turn' || !turn.items?.length) {
		return turn;
	}
	const items = turn.items;
	const last = items[items.length - 1];
	if (!last || last.kind !== 'assistant') {
		return turn;
	}
	const committed = last.message.text.trimEnd();
	const shown = streaming.trimEnd();
	if (!shown || !committed.startsWith(shown)) {
		return turn;
	}
	return {...turn, items: items.slice(0, -1)};
}

/**
 * messages 引用未变、只改流式尾巴时，复用历史 block，只替换最后一块 turn。
 */
export function patchTranscriptTail(
	blocks: TranscriptBlock[],
	opts?: {
		streamingText?: string;
		isLoading?: boolean;
		statusText?: string;
		reasoningText?: string;
	},
): TranscriptBlock[] {
	const streaming = opts?.streamingText?.trim()
		? opts.streamingText
		: undefined;
	const thinking =
		opts?.isLoading && opts?.reasoningText?.trim()
			? opts.reasoningText.trim()
			: undefined;

	if (blocks.length === 0) {
		if (!streaming && !thinking) {
			return blocks;
		}
		return [
			{
				kind: 'turn',
				id: 'turn-tail',
				items: [],
				streaming,
				thinking,
				active: true,
			},
		];
	}

	const last = blocks[blocks.length - 1]!;
	if (streaming || thinking) {
		if (last.kind === 'turn') {
			if (
				last.streaming === streaming &&
				last.thinking === thinking &&
				last.active
			) {
				const stripped = stripDrainDuplicateProse(last, streaming);
				if (stripped === last) {
					return blocks;
				}
				const next = blocks.slice(0, -1);
				next.push(stripped);
				return next;
			}
			const next = blocks.slice(0, -1);
			next.push(
				stripDrainDuplicateProse(
					{
						...last,
						streaming,
						thinking,
						active: true,
					},
					streaming,
				),
			);
			return next;
		}
		const next = blocks.slice();
		next.push({
			kind: 'turn',
			id: 'turn-tail',
			items: [],
			streaming,
			thinking,
			active: true,
		});
		return next;
	}

	if (opts?.isLoading && last.kind === 'turn') {
		if (last.active && last.streaming === undefined && last.thinking === undefined) {
			return blocks;
		}
		const next = blocks.slice(0, -1);
		next.push({
			...last,
			streaming: undefined,
			thinking: undefined,
			active: true,
		});
		return next;
	}

	if (
		!opts?.isLoading &&
		!streaming &&
		!thinking &&
		last.kind === 'turn' &&
		(last.active || last.streaming || last.thinking)
	) {
		const next = blocks.slice(0, -1);
		next.push({
			...last,
			streaming: undefined,
			thinking: undefined,
			active: false,
		});
		return next;
	}

	return blocks;
}
