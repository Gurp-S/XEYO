/**
 * syntheticTranscript.ts — /bench/chat 合成转录生成器（P0 测量设施）。
 *
 * 产出确定性的、贴近真实 XEYO 对话形态的 ChatMessage[]：
 * - 每轮以 user 消息开头（rounds / TurnRail 分组依赖）；
 * - assistant 回复是混合 CJK 散文 + Markdown 结构（标题/列表/表格/引用/
 *   行内代码/代码围栏），与真实转录走同一条 MarkdownView 渲染管线；
 * - 部分轮次插入 tool 行（toolInput/toolStatus/result）与 isThought 推理块，
 *   覆盖 ActivityLog / 工具视图 / reasoning 渲染路径；
 * - 内容只含字符串，不发起任何网络/IDB 请求。
 *
 * 同一 seed 必然产出同一转录 —— 基线与优化后可逐字节对齐对比。
 */

import type {ChatMessage} from '@/lib/types';

/** mulberry32 — 小而快的确定性 PRNG。 */
export function mulberry32(seed: number): () => number {
	let a = seed >>> 0;
	return () => {
		a |= 0;
		a = (a + 0x6d2b79f5) | 0;
		let t = Math.imul(a ^ (a >>> 15), 1 | a);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

type Rng = () => number;

function pick<T>(rng: Rng, arr: readonly T[]): T {
	return arr[Math.floor(rng() * arr.length) % arr.length]!;
}

function pickInt(rng: Rng, min: number, max: number): number {
	return min + Math.floor(rng() * (max - min + 1));
}

const USER_ASKS = [
	'帮我看下 MessageList 为什么切会话会闪一下，给出不改视觉的修法。',
	'这个模块的渲染路径再分析一遍，只输出结论和风险点。',
	'解释一下 stickyContract C1-C7 现在各自覆盖什么场景。',
	'把这段报错翻译成人话：ResizeObserver loop completed with undelivered notifications。',
	'帮我审一下这个 PR 的滚动跟尾实现，重点看过帧调度。',
	'总结一下今天我们定的性能预算，列出验收口径。',
	'roundHeights 的订阅回调为什么不能同步写 React state？',
	'给 VirtualRoundList 写一组单测，覆盖窗口边界与强制挂载。',
	'这个正则为什么会把 CJK 标点切开？换一种写法。',
	'对比一下 requestIdleCallback 与 rAF 分帧在启动路径的取舍。',
	'帮我看看这个崩溃栈：Cannot read properties of null (reading scrollTop)。',
	'把 tool_result 的 <pre> 做窗口化会不会影响搜索高亮？',
];

const PROSE_LEADS = [
	'结论先行：这个问题出在订阅粒度，而不是渲染本身。',
	'先说风险点，再给可回退的实施顺序。',
	'当前实现有三层：调度层、分组层、挂载层，逐层看。',
	'我核对了一遍调用点，行为差异集中在两处边缘情况。',
	'这个改动可以做成纯函数下沉，UI 层零感知。',
	'从帧预算倒推：每帧留给 JS 的时间不到一半，必须合并写入。',
	'基准数据显示长会话的成本随轮数线性放大，先砍常数项。',
	'这里有一个隐性契约：sticky 层不能用 content-visibility。',
];

const PROSE_BODIES = [
	'把稳定区块和活动区块分开：历史 Markdown、已完成的代码与工具状态都是稳定区块；当前回复末尾、滚动跟随与 sticky 气泡属于活动区块。优化只落在活动区块，稳定区块做引用级缓存。',
	'关键在帧内顺序：先读布局（scrollTop、clientHeight），再写（窗口边界、spacer 高度），读写分离可以避免布局抖动。高度实测回写只写 Map，不落 React state，窗口边界不变就零渲染。',
	'订阅面要打平：zustand selector 返回嵌套对象会破坏 useShallow，症状是无限循环或整树重渲。高频流式字段改 transient subscribe，绕开 React 渲染提交。',
	'解析结果按（文本引用 + variant）做 LRU：settled 消息的解析树只依赖文本引用，引用不变直接复用；流式期间增量化，把每帧成本压到 O(增量)。',
	'窗口化只允许试探非 sticky 层：工具输出 <pre>、ActivityLog 展开体、条目内部。round/sticky 层禁止 content-visibility，会和 sticky+clip-path 打孔打架。',
	'数据层避免全量覆盖：replaceMessages 在热路径上会冲掉增量写入，persistHot 已有 debounce，增量 patch 只需要补齐合并语义。',
];

const CODE_TS = `export function mergeIntervals(list: RoundWindow[]): RoundWindow[] {
	if (list.length === 0) {
		return [];
	}
	const sorted = [...list].sort((a, b) => a.start - b.start || a.end - b.end);
	const out: RoundWindow[] = [{...sorted[0]!}];
	for (let i = 1; i < sorted.length; i += 1) {
		const last = out[out.length - 1]!;
		const cur = sorted[i]!;
		if (cur.start <= last.end) {
			last.end = Math.max(last.end, cur.end);
		} else {
			out.push({...cur});
		}
	}
	return out;
}`;

const CODE_PY = `def compute_prefix(round_ids: list[str], heights: dict[str, int]) -> list[int]:
    prefix = [0]
    acc = 0
    for rid in round_ids:
        acc += heights.get(rid, DEFAULT_ROUND_HEIGHT)
        prefix.append(acc)
    return prefix


def window_for(prefix: list[int], scroll_top: int, viewport_h: int) -> tuple[int, int]:
    overscan = 900
    top = max(0, scroll_top - overscan)
    bottom = scroll_top + viewport_h + overscan
    return bisect_index(prefix, top), bisect_index(prefix, bottom) + 1`;

const CODE_JSON = `{
  "version": 3,
  "rules": [
    {"id": "C1", "when": "prompt sticky top", "do": "hide in-flow chip"},
    {"id": "C2", "when": "punch-through", "do": "clip-path on content layer"},
    {"id": "C3", "when": "overlay pin", "do": "sync text into overlay host"}
  ]
}`;

const TOOL_NAMES = ['Read', 'Grep', 'Glob', 'Edit', 'Bash', 'TodoWrite', 'WebSearch'] as const;

const TOOL_RESULT_POOLS: readonly ((rng: Rng) => string)[] = [
	rng => {
		const lines = pickInt(rng, 8, 40);
		const out: string[] = [];
		for (let i = 0; i < lines; i += 1) {
			out.push(
				`${String(i + 1).padStart(3, '0')}  export const round = ${i}; // xy-round-transcript-layer`,
			);
		}
		return out.join('\n');
	},
	rng =>
		JSON.stringify(
			{
				ok: true,
				matched: pickInt(rng, 1, 96),
				files: [
					'gui/src/components/messageList/MessageList.tsx',
					'gui/src/components/VirtualRoundList.tsx',
					'gui/src/lib/roundVirtual.ts',
				],
				tookMs: pickInt(rng, 4, 380),
			},
			null,
			2,
		),
	rng => {
		const lines = pickInt(rng, 20, 120);
		const out: string[] = ['[xeyo] engine attach ok', '[xeyo] stream open'];
		for (let i = 0; i < lines; i += 1) {
			out.push(
				`[xeyo:${pickInt(rng, 100, 999)}] frame ${i} reads=${pickInt(rng, 0, 12)} writes=${pickInt(rng, 0, 6)} dropped=false`,
			);
		}
		return out.join('\n');
	},
];

function cjkParagraph(rng: Rng, sentences: number): string {
	const parts: string[] = [];
	for (let i = 0; i < sentences; i += 1) {
		parts.push(pick(rng, PROSE_LEADS));
		parts.push(pick(rng, PROSE_BODIES));
	}
	return parts.join('');
}

function markdownReply(rng: Rng, shape: 'light' | 'medium' | 'heavy'): string {
	const out: string[] = [];
	out.push(`## ${pick(rng, ['排查路径', '实施顺序', '结论与风险', '设计取舍'])}`);
	out.push('');
	out.push(cjkParagraph(rng, shape === 'light' ? 1 : 2));
	out.push('');
	const listItems = shape === 'light' ? 2 : pickInt(rng, 3, 5);
	for (let i = 0; i < listItems; i += 1) {
		out.push(`${i + 1}. ${pick(rng, PROSE_BODIES)}`);
	}
	out.push('');
	if (shape !== 'light') {
		out.push('| 阶段 | 预算 | 现状 |');
		out.push('| --- | --- | --- |');
		out.push(`| token 帧 | <8ms | ${pickInt(rng, 3, 22)}ms |`);
		out.push(`| 会话切换 | <50ms | ${pickInt(rng, 18, 140)}ms |`);
		out.push(`| 滚动帧 | <=16ms | ${pickInt(rng, 9, 34)}ms |`);
		out.push('');
	}
	if (shape === 'heavy') {
		out.push(`\`\`\`${pick(rng, ['ts', 'python', 'json'])}`);
		out.push(pick(rng, [CODE_TS, CODE_PY, CODE_JSON]));
		out.push('```');
		out.push('');
		out.push(cjkParagraph(rng, 1));
		out.push('');
	}
	out.push(`> 注意：${pick(rng, PROSE_BODIES)}`);
	out.push('');
	out.push(`细节见 \`gui/src/${pick(rng, ['lib/roundVirtual.ts', 'components/VirtualRoundList.tsx', 'stores/chat/spaceSessionSlice.ts'])}\`，或直接看 [roundVirtual](gui/src/lib/roundVirtual.ts)。`);
	return out.join('\n');
}

function streamReply(rng: Rng): string {
	const out: string[] = [];
	out.push('## 基准回放：流式尾部渲染');
	out.push('');
	out.push(cjkParagraph(rng, 2));
	out.push('');
	out.push('- 增量 remend 只扫尾部未配对标记，不重扫全文；');
	out.push('- 分块解析复用同一 lex 缓存，fade 计划与 Streamdown 共享；');
	out.push('- 高度回写按帧合并，窗口不变零渲染。');
	out.push('');
	out.push('```ts');
	out.push(CODE_TS);
	out.push('```');
	out.push('');
	out.push(cjkParagraph(rng, 1));
	out.push('');
	out.push('| 阶段 | 预算 |');
	out.push('| --- | --- |');
	out.push('| token 帧 | <8ms |');
	out.push('| 会话切换 | <50ms |');
	return out.join('\n');
}

export type SyntheticTranscriptOptions = {
	/** 轮数（每轮 = 1 条 user + 若干 assistant/tool/system 行）。 */
	rounds: number;
	seed?: number;
};

/**
 * 生成 N 轮合成转录。确定性：同 rounds + seed 产出逐字节相同。
 * 轮次形态分布（由 rng 驱动，跨轮混合）：
 * - ~12% light（短问答）、~58% medium（中等 Markdown）、~18% heavy（长代码围栏）、
 *   ~12% tool（含工具行 + 双段散文，偶发 isThought / system / reasoningBefore）。
 */
export function buildSyntheticMessages(options: SyntheticTranscriptOptions): ChatMessage[] {
	const {rounds, seed = 20240501} = options;
	const rng = mulberry32(seed);
	const messages: ChatMessage[] = [];
	let createdAt = 1_700_000_000_000;

	const push = (m: Omit<ChatMessage, 'createdAt'>) => {
		createdAt += pickInt(rng, 900, 1500);
		messages.push({...m, createdAt});
	};

	for (let round = 0; round < rounds; round += 1) {
		const roll = rng();
		const shape: 'light' | 'medium' | 'heavy' | 'tool' =
			roll < 0.12 ? 'light' : roll < 0.7 ? 'medium' : roll < 0.88 ? 'heavy' : 'tool';

		const askPrefix = shape === 'heavy' ? '这块要看代码，' : '';
		push({
			id: `syn-u-${round}`,
			role: 'user',
			text: `${askPrefix}${pick(rng, USER_ASKS)}`,
		});

		if (shape === 'tool') {
			if (rng() < 0.5) {
				push({
					id: `syn-t-${round}-0`,
					role: 'assistant',
					text: pick(rng, PROSE_LEADS),
					isThought: true,
				});
			}
			push({
				id: `syn-a-${round}-1`,
				role: 'assistant',
				text: cjkParagraph(rng, 1),
			});
			const toolCount = rng() < 0.7 ? 1 : 2;
			for (let t = 0; t < toolCount; t += 1) {
				const toolName = pick(rng, TOOL_NAMES);
				push({
					id: `syn-tool-${round}-${t}`,
					role: 'tool',
					toolName,
					toolInput: JSON.stringify({
						path: `gui/src/lib/${pick(rng, ['roundVirtual', 'frameScheduler', 'roundHeights'])}.ts`,
						pattern: pick(rng, ['scheduleFrameRead', 'setRoundHeight', 'roundWindowFor']),
					}),
					toolStatus: 'done',
					text: pick(rng, TOOL_RESULT_POOLS)(rng),
					...(rng() < 0.35
						? {reasoningBefore: cjkParagraph(rng, 1), thoughtMs: pickInt(rng, 400, 5200)}
						: {}),
				});
			}
			push({
				id: `syn-a-${round}-2`,
				role: 'assistant',
				text: markdownReply(rng, 'medium'),
			});
			if (rng() < 0.12) {
				push({
					id: `syn-sys-${round}`,
					role: 'system',
					text: `已会话内提醒：tool ${pick(rng, TOOL_NAMES)} 输出被截断到 ${pickInt(rng, 2, 40)} 行。`,
				});
			}
			continue;
		}

		push({
			id: `syn-a-${round}`,
			role: 'assistant',
			text: markdownReply(rng, shape),
		});
	}

	return messages;
}

/** 供 token 基准驱动的流式回复全文（与真实直播走同一渲染管线）。 */
export function buildSyntheticStreamReply(seed = 77): string {
	const rng = mulberry32(seed);
	return streamReply(rng);
}
