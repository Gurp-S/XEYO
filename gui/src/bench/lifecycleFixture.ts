/**
 * lifecycleFixture.ts — /bench/chat?scenario=lifecycle 的确定性活动样张（dev-only）。
 *
 * 存在的理由：`?rounds=N` 的合成转录只产出 1~2 个工具步，无法用来判定
 * activity.css 的工具族语义 / 长输出封顶 / 错误可读性 / 最终回答分离。
 * 本文件一次铺满一条真实工作流的全部形态，顺序即阅读顺序：
 *
 *   用户请求 → 思考 → 计划（TodoWrite）→ 多次读文件 → 搜索 / glob
 *   → 编辑（真 diff +N/−N）→ 新建文件 → 命令（≥300 行长输出）
 *   → 失败测试 → 错误行（含诊断入口）→ 重试成功 → 子 Agent 派工 ×3（结果条）
 *   → 任务收尾（done-on）→ 最终回答（标题 / 列表 / 表格 / 行内代码）
 *
 * 铁律：
 * - 纯字符串产物，不发网络、不碰 IDB；同一参数必然产出同一数组（可逐字节对齐）。
 * - 只喂 ChatMessage 形态的数据，走生产同一条 groupTranscript → segmentTurn →
 *   ActivityLog 管线；不为了测量伪造 DOM。
 * - 只在 /bench/chat 的 scenario 分支里被引用，不进产品路径。
 */

import type {ChatMessage, ToolStatus} from '@/lib/types';
import type {MultiAgentTaskView} from '@/lib/api';

/** 固定起点，保证 createdAt 稳定（done-on 的「worked for」时长依赖它）。 */
const T0 = 1_790_514_720_000; // 2026-09-27 21:12 (+08:00)

/** 每条消息推进的毫秒数（确定性，不用 rng，避免任何跨版本漂移）。 */
const STEP_MS: readonly number[] = [
	3_100, 1_900, 2_400, 1_200, 1_100, 1_300, 900, 1_000, 2_200, 4_800, 5_600,
	1_400, 600, 3_300, 7_900, 2_600, 2_100, 1_800, 60_000, 12_000, 4_400, 900,
	26_000, 3_600, 1_500, 40_000, 5_200, 2_000,
];

export type LifecycleOptions = {
	/**
	 * 'live' = 工作仍在进行：末尾挂一条 running 的 Bash（无结果）。
	 * 该形态走 groupTranscript 的 active 尾部，渲染成交错轨 + Working 顶栏；
	 * 'settled'（缺省）= 全部落定，渲染成 done-on 折叠卡 + 最终回答；
	 * 'stopped' = 停在失败那一步：失败行是轨里的最后一条（测收尾竖条 / 加粗动词）。
	 */
	live?: boolean;
	phase?: 'settled' | 'live' | 'stopped';
};

type ToolSpec = {
	id: string;
	name: string;
	input: unknown;
	result: string;
	status: ToolStatus;
	toolUseId?: string;
	reasoningBefore?: string;
	thoughtMs?: number;
};

/** 320 行命令输出：足够顶破任何没有封顶的容器。 */
function longPytestOutput(): string {
	const lines: string[] = [
		'$ py -3.11 -m pytest tests/wsc -q -x --no-header -p no:randomly',
		'platform win32 -- Python 3.11.9, pytest-8.2.0, pluggy-1.5.0',
		'rootdir: D:\\lea\\XenYon code\\python',
		'configfile: pyproject.toml',
		'plugins: anyio-4.3.0, asyncio-0.23.7, cov-5.0.0',
		'collected 318 items',
		'',
	];
	const modules = [
		'tests/wsc/test_cadence.py',
		'tests/wsc/test_projection.py',
		'tests/wsc/test_fold_emit.py',
		'tests/wsc/test_path_index.py',
		'tests/test_runtime_c2.py',
	];
	for (let i = 0; i < 300; i += 1) {
		const mod = modules[i % modules.length]!;
		const mark = i % 37 === 13 ? 's' : i % 53 === 41 ? 'x' : '.';
		lines.push(
			`[runner:${String(1000 + (i % 900)).padStart(4, '0')}] ${mark} ${mod}::case_${String(i).padStart(3, '0')} elapsed=${(0.4 + (i % 17) * 0.13).toFixed(2)}s tokens_in=${9_400 + i * 37} tokens_out=${120 + i * 3}`,
		);
	}
	lines.push('');
	lines.push('================================ FAILURES ================================');
	lines.push('___ test_cadence_backpressure_drops_only_cold_layer[win32-py3.11-x86_64] ___');
	lines.push('    assert folded.hot_tokens <= budget');
	lines.push('E   assert 12_840 <= 12_000');
	lines.push('tests/wsc/test_cadence.py:412: AssertionError');
	lines.push('=========== short test summary info ===========');
	lines.push('FAILED tests/wsc/test_cadence.py::test_cadence_backpressure_drops_only_cold_layer');
	lines.push('1 failed, 315 passed, 2 skipped, 1 xfailed in 48.16s (0:00:48)');
	return lines.join('\n');
}

/** 真 diff（编辑行）：+N/−N 由 result 头部的显式统计给出。 */
const EDIT_RESULT = [
	'The file gui/src/styles/activity.css has been updated successfully. +21 -7',
	'',
	'```diff',
	'--- a/gui/src/styles/activity.css',
	'+++ b/gui/src/styles/activity.css',
	'@@ -100,9 +100,17 @@',
	' /* —— 3.1 命令 —— */',
	'-/* 原来命令与读共用同一档字号，扫读时看不出层级。 */',
	'-/* TODO: 收紧标记列 */',
	'+/* 命令族：$ 前缀 + ink 前景 + 中等密度，与廉价操作拉开一档。 */',
	'+.xy-activity-split .xy-split-step:has(.xy-split-preview.is-cmd) {',
	'+\tpadding-block: var(--xy-act-pad-body);',
	'+}',
	'+',
	'+.xy-activity-split .xy-split-step:has(.xy-split-preview.is-cmd) .xy-morph {',
	'+\tfont-size: var(--xy-act-body);',
	'+}',
	' .xy-split-step {',
	'-\tborder-bottom: 1px dashed var(--xy-line);',
	'-\tpadding-block: 2px;',
	'+\tborder-bottom: 0;',
	'+\tpadding-block: var(--xy-act-pad-quiet);',
	' }',
	'```',
].join('\n');

const WRITE_RESULT = [
	'File created successfully: gui/src/bench/lifecycleFixture.ts',
	'（新建文件，共 168 行） +168 -0',
	'',
	'```diff',
	'--- /dev/null',
	'+++ b/gui/src/bench/lifecycleFixture.ts',
	'@@ -0,0 +1,12 @@',
	'+/** lifecycleFixture.ts — 确定性活动样张（dev-only）。 */',
	"+import type {ChatMessage} from '@/lib/types';",
	'+',
	'+const T0 = 1_700_000_000_000;',
	'+',
	'+export function buildLifecycleMessages(): ChatMessage[] {',
	'+\treturn [];',
	'+}',
	'```',
].join('\n');

const FIRST_THOUGHT = [
	'先把问题拆成三件互不相干的事：动词从哪来、族签名靠什么钩子落、封顶在哪个容器生效。',
	'动词不是 DOM 属性，只是 MorphVerb 里的文本节点，所以任何「按工具族上样式」的规则都必须先找到一个真实存在的类名钩子；',
	'读到的结果是：只有 is-failed / is-ok / is-waiting / is-cmd / :has(.tabular-nums) / :has(+ .xy-agent-done-list) 这六个是可靠的。',
	'命令族的 320 行输出一定会把没封顶的 <pre> 顶开，先在展开体上给硬顶 + 内部滚动，再看会不会把页面横向撑破。',
].join('');

const EDIT_THOUGHT = [
	'改动行必须比读/搜响一档，但只能响在密度与前景上，不能靠彩色：轨里一旦同时出现读绿改红，扫读就会先被颜色抓住而不是被结构抓住。',
	'+/− 徽章本身就是「这是改动」的事实信号，所以把它当作改动族的第二钩子，与 is-ok 并联。',
].join('');

const READ_SPECS: ReadonlyArray<[string, string, number, number]> = [
	['ActivityLog.tsx', 'gui/src/components/ActivityLog.tsx', 380, 520],
	['steps.ts', 'gui/src/lib/toolActivity/steps.ts', 1, 186],
	['todos.ts', 'gui/src/lib/toolActivity/todos.ts', 280, 380],
	['revert-compat.css', 'gui/src/styles/revert-compat.css', 295, 460],
];

function readOutput(name: string, from: number, to: number): string {
	const lines: string[] = [];
	for (let n = from; n <= Math.min(to, from + 26); n += 1) {
		lines.push(
			`${String(n).padStart(4, ' ')}\texport const ${name.replace(/\W/g, '_').toLowerCase()}_line_${n} = ${n * 7}; // xy-bench-fixture`,
		);
	}
	lines.push(`… (${to - from - 26} more lines)`);
	return lines.join('\n');
}

function toolSpecs(): ToolSpec[] {
	const specs: ToolSpec[] = [];

	specs.push({
		id: 'lc-todo',
		name: 'TodoWrite',
		toolUseId: 'toolu_lc_01',
		input: {
			todos: [
				{content: '读 ActivityLog / steps.ts，确认动词与族钩子来源', status: 'completed', activeForm: '通读活动轨渲染管线'},
				{content: '给改动 / 命令族各上一条真实钩子规则', status: 'completed', activeForm: '补工具族签名'},
				{content: '长输出展开体封顶 + 内部滚动', status: 'in_progress', activeForm: '封顶长输出'},
				{content: '错误行改为 2px 行首竖条，不铺红底', status: 'pending', activeForm: '重做错误行'},
				{content: '跑 vitest + playwright 实测，回填数据', status: 'pending', activeForm: '实测回填'},
			],
		},
		result: 'Todos have been modified successfully. Ensure that you continue to use the todo list to track your progress.',
		status: 'done',
	});

	READ_SPECS.forEach(([name, path, from, to], i) => {
		specs.push({
			id: `lc-read-${i + 1}`,
			name: 'Read',
			toolUseId: `toolu_lc_r${i}`,
			input: {file_path: path, offset: from, limit: to - from},
			result: readOutput(name, from, to),
			status: 'done',
		});
	});

	specs.push({
		id: 'lc-grep',
		name: 'Grep',
		toolUseId: 'toolu_lc_g1',
		input: {pattern: 'xy-split-(step|preview|bullet)', path: 'gui/src', glob: '*.tsx'},
		result: [
			'gui/src/components/ActivityLog.tsx',
			'   441: 					\'xy-split-step\',',
			'   461: 				<span className="xy-split-bullet" aria-hidden>',
			'   485: 						className={cn(\'xy-split-preview\', isCommand && \'is-cmd\')}',
			'',
			'gui/src/components/messageList/RoundHost.tsx',
			'   504: 								className="xy-workflow-fold"',
			'',
			'Found 4 matches across 2 files.',
		].join('\n'),
		status: 'done',
	});

	specs.push({
		id: 'lc-glob',
		name: 'Glob',
		toolUseId: 'toolu_lc_gl1',
		input: {pattern: 'gui/src/styles/*.css'},
		result: [
			'gui/src/styles/activity.css',
			'gui/src/styles/chat.css',
			'gui/src/styles/revert-compat.css',
			'gui/src/styles/settings.css',
			'gui/src/styles/tokens.css',
			'gui/src/styles/workbench.css',
			'gui/src/styles/workflow-split.css',
			'(7 files)',
		].join('\n'),
		status: 'done',
	});

	specs.push({
		id: 'lc-edit',
		name: 'Edit',
		toolUseId: 'toolu_lc_e1',
		input: {
			file_path: 'gui/src/styles/activity.css',
			old_string: '/* TODO: 收紧标记列 */',
			new_string: '/* 命令族：$ 前缀 + ink 前景 + 中等密度 */',
			replace_all: false,
		},
		result: EDIT_RESULT,
		status: 'done',
		reasoningBefore: EDIT_THOUGHT,
		thoughtMs: 8_400,
	});

	specs.push({
		id: 'lc-write',
		name: 'Write',
		toolUseId: 'toolu_lc_w1',
		input: {file_path: 'gui/src/bench/lifecycleFixture.ts', content: 'x'.repeat(640)},
		result: WRITE_RESULT,
		status: 'done',
	});

	specs.push({
		id: 'lc-cmd',
		name: 'Bash',
		toolUseId: 'toolu_lc_b1',
		input: {command: 'py -3.11 -m pytest tests/wsc -q -x --no-header'},
		result: longPytestOutput(),
		status: 'done',
	});

	specs.push({
		id: 'lc-test-fail',
		name: 'Bash',
		toolUseId: 'toolu_lc_b2',
		input: {command: 'cd gui && npx vitest run src/components'},
		result: [
			'[error] exit code 1',
			'RUN  v3.2.4 D:/lea/XenYon code/gui',
			'',
			' ✓ src/components/AgentDoneBars.test.tsx (7 tests) 412ms',
			' ❯ src/components/FilesChanged.test.tsx (5 tests | 2 failed) 903ms',
			'   × FilesChanged > 展开时画出行内 diff 行 ±Npx',
			"     → expected '184px' to be '16px' // Object.is equality",
			'   × FilesChanged > 收起态两行不重叠',
			"     → TypeError: Cannot read properties of undefined (reading 'getBoundingClientRect')",
			'',
			' Test Files  1 failed | 43 passed (44)',
			'      Tests  2 failed | 611 passed (613)',
			'   Duration  18.42s',
		].join('\n'),
		status: 'error',
	});

	specs.push({
		id: 'lc-read-fail',
		name: 'Read',
		toolUseId: 'toolu_lc_rf',
		input: {file_path: 'gui/src/styles/activity.css', offset: 900, limit: 40},
		result:
			'[error] File does not exist. Note: your current working directory is D:\\lea\\XenYon code.',
		status: 'error',
	});

	specs.push({
		id: 'lc-read-retry',
		name: 'Read',
		toolUseId: 'toolu_lc_rr',
		input: {file_path: 'gui/src/styles/activity.css', offset: 400, limit: 71},
		result: readOutput('activity.css', 400, 471),
		status: 'done',
	});

	specs.push({
		id: 'lc-cmd-retry',
		name: 'Bash',
		toolUseId: 'toolu_lc_b3',
		input: {command: 'cd gui && npx vitest run src/components'},
		result: [
			'RUN  v3.2.4 D:/lea/XenYon code/gui',
			'',
			' ✓ src/components/FilesChanged.test.tsx (5 tests) 812ms',
			' ✓ src/components/AgentDoneBars.test.tsx (7 tests) 398ms',
			' ✓ src/components/TurnRail.test.tsx (12 tests) 1_204ms',
			'',
			' Test Files  44 passed (44)',
			'      Tests  613 passed (613)',
			'   Duration  17.88s',
		].join('\n'),
		status: 'done',
	});

	const agents: Array<[string, string, string]> = [
		['lc-agent-1', 'task_wsc_fold', '复核 WSC V2 热头发射路径：找出不依赖 LLM 的确定性折叠判据'],
		['lc-agent-2', 'task_gui_probe', '写 Playwright 探针：逐族采样 computed style 与像素级对比度'],
		['lc-agent-3', 'task_paths_audit', '审计 mainPaths 权限/reattach 两条红测的归属与结构根因'],
	];
	for (const [id, taskId, desc] of agents) {
		specs.push({
			id,
			name: 'Agent',
			toolUseId: `toolu_${id}`,
			input: {task_id: taskId, description: desc, subagent_type: 'general-purpose', prompt: '只做研究与度量，不改文件。'},
			result: `[${taskId}] 完成：3 条结论 + 1 份逐点结果 JSON。`,
			status: 'done',
		});
	}

	return specs;
}

function toMessage(spec: ToolSpec, createdAt: number): ChatMessage {
	return {
		id: spec.id,
		role: 'tool',
		toolName: spec.name,
		toolUseId: spec.toolUseId,
		toolInput: JSON.stringify(spec.input),
		toolStatus: spec.status,
		text: spec.result,
		...(spec.reasoningBefore ? {reasoningBefore: spec.reasoningBefore} : {}),
		...(spec.thoughtMs ? {thoughtMs: spec.thoughtMs} : {}),
		createdAt,
	};
}

export const FINAL_ANSWER = [
	'## 结论：四条族规则里只有两条站得住',
	'',
	'落定态实测下来，读/搜/子 Agent 派工三族在计算样式上完全同签名——不是配色问题，是 DOM 里没有可选的族钩子。改动族与命令族是站得住的，因为它们各自有真实存在的类名可以锚。',
	'',
	'### 关键证据',
	'',
	'1. `xy-morph` 只把动词渲染成文本节点，`Read` 与 `Grepped` 的 `color` / `font-family` / `font-size` 三项计算值逐字节相同；',
	'2. 命令族的 `$ ` 前缀来自 `.xy-split-preview.is-cmd::before`，这是轨里唯一由 markup 保证的族标记；',
	'3. 改动行同时命中 `.is-ok` 与 `:has(.tabular-nums)`，所以它是唯一有两条独立钩子的族；',
	'4. 失败命令因为动词被统一改写成 `Failed`，反而丢掉了 `.is-cmd`——命令族在它最需要被认出来的那一格塌了。',
	'',
	'| 族 | 钩子 | 落定态可见 | 判定 |',
	'| --- | --- | --- | --- |',
	'| 读 | 无 | 是 | 与搜不可分 |',
	'| 搜 | 无 | 是 | 与读不可分 |',
	'| 改 | `.is-ok` + `:has(.tabular-nums)` | 是 | 成立 |',
	'| 命令 | `.is-cmd` | 是 | 成立（失败命令除外） |',
	'| 错误 | `.is-failed` | 是 | 成立 |',
	'| 重试 | 无 | 是 | 与读不可分 |',
	'| 子 Agent | `:has(+ .xy-agent-done-list)` | 否（卡片不在轨内） | 落定态失效 |',
	'',
	'> 也就是说：现在这份样式表写的是一整套族语义，真正能在用户实际看到的落定视图里生效的，只有改动 / 命令 / 错误三族。',
	'',
	'### 下一步',
	'',
	'要么补 markup 钩子（把工具族作为 `data-*` 透出到 `xy-split-step` 上），要么承认轨只有「安静 / 响 / 出错」三档，把剩下五族的规则删掉。留着不生效的规则不是无害的——它是下一轮改动里最容易被误判为「已经改过」的那部分。',
].join('\n');

/** 子 Agent 结果条（3 条一批，与三个 Agent 工具步一一对应）。 */
export function buildLifecycleAgentTasks(): MultiAgentTaskView[] {
	const base = T0 + 120_000;
	return [
		{
			uid: 'lc-task-1',
			taskId: 'task_wsc_fold',
			agentId: 'agent_wsc_1',
			desc: '复核 WSC V2 热头发射路径：找出不依赖 LLM 的确定性折叠判据',
			status: 'done',
			result: '3 条结论：折叠判据可确定性化；预算缺口来自冷层引用不稳定；B4 索引在同预算配对下胜出。',
			readOnly: true,
			batchAt: base,
			tokensUsed: 48_213,
			costCny: 0.42,
		},
		{
			uid: 'lc-task-2',
			taskId: 'task_gui_probe',
			agentId: 'agent_gui_2',
			desc: '写 Playwright 探针：逐族采样 computed style 与像素级对比度',
			status: 'done',
			result: '探针已产出 4 组 JSON；像素级对比度需沿祖先链合成，白底假设会造出假失败。',
			scope: ['gui/_design_drafts/'],
			filesTouched: ['gui/_design_drafts/reaudit-20260927/r4/probe.mjs'],
			batchAt: base + 1_000,
			tokensUsed: 61_940,
			costCny: 0.58,
		},
		{
			uid: 'lc-task-3',
			taskId: 'task_paths_audit',
			agentId: 'agent_paths_3',
			desc: '审计 mainPaths 权限/reattach 两条红测的归属与结构根因',
			status: 'failed',
			reason: 'Permission denied: python/tests 不在本会话允许写入的路径前缀内',
			batchAt: base + 2_000,
			tokensUsed: 12_007,
			costCny: 0.11,
		},
	];
}

/**
 * 完整生命周期样张。
 * 返回顺序即渲染顺序；phase 只改变尾部（settled 全量 / live 追一条在途命令 /
 * stopped 停在失败行），前面的消息逐字节相同。
 */
export function buildLifecycleMessages(options: LifecycleOptions = {}): ChatMessage[] {
	const phase = options.phase ?? (options.live ? 'live' : 'settled');
	const messages: ChatMessage[] = [];
	let cursor = T0;
	const at = () => {
		const ms = STEP_MS[messages.length % STEP_MS.length]!;
		cursor += ms;
		return cursor;
	};

	// —— 轮 1：无工具的短问答（对照用：这一轮不该出现任何族规则）——
	messages.push({
		id: 'lc1-user',
		role: 'user',
		text: '先不干活：这个仓库里 activity.css 是什么时候被引入的？一句话。',
		createdAt: at(),
	});
	messages.push({
		id: 'lc1-a',
		role: 'assistant',
		text:
			'它由 `styles/entry.css` 末位在 `revert-compat.css`、`workbench.css` 之后引入，顺序即层叠优先级，所以它覆盖前两者的同名声明。',
		createdAt: at(),
	});

	// —— 轮 2：完整生命周期 ——
	messages.push({
		id: 'lc2-user',
		role: 'user',
		text:
			'把 ActivityLog 的工具族语义补上：读/搜要退到背景，命令/改动要抬上来，长输出必须封顶，错误别铺红底。改完把测试跑一遍，最后把哪些族真的成立讲清楚，不成立的直说。',
		createdAt: at(),
	});

	// 思考（独立 reasoning 块 → Thought 行）
	messages.push({
		id: 'lc-thought',
		role: 'assistant',
		text: FIRST_THOUGHT,
		isThought: true,
		thoughtMs: 11_800,
		createdAt: at(),
	});

	for (const spec of toolSpecs()) {
		messages.push(toMessage(spec, at()));
		if (phase === 'stopped' && spec.id === 'lc-read-fail') {
			break;
		}
	}
	if (phase === 'stopped') {
		// 停在失败这一步：失败行是轨里的最后一条。
		return messages;
	}

	// 工具批次之间的过程旁白（落定后会被 isProcessNarration 折掉）
	messages.push({
		id: 'lc-narration',
		role: 'assistant',
		text: '让我先看一眼活动轨的展开体，再决定封顶放在哪一层。',
		createdAt: at(),
	});

	if (phase === 'live') {
		// 在途命令：只有 live 形态存在（落定态不该有 running 行）。
		messages.push({
			id: 'lc-cmd-live',
			role: 'tool',
			toolName: 'Bash',
			toolUseId: 'toolu_lc_bl',
			toolInput: JSON.stringify({command: 'cd gui && npx tsc -b --pretty false'}),
			toolStatus: 'running',
			text: '',
			createdAt: at(),
		});
		return messages;
	}

	// 收尾前的说明（落定后只保留最后一条 prose）
	messages.push({
		id: 'lc-pre-final',
		role: 'assistant',
		text: '我把四条族规则按实测收拢成两条能生效的，另外三条需要 markup 钩子才能继续。',
		createdAt: at(),
	});

	messages.push({
		id: 'lc-final',
		role: 'assistant',
		text: FINAL_ANSWER,
		createdAt: at(),
	});

	return messages;
}

/** live 形态的流式尾部（与真实直播同一条 StreamingMarkdown 管线）。 */
export const LIFECYCLE_STREAM_TEXT = [
	'### 还在跑的最后一步',
	'',
	'`npx tsc -b` 还没返回；等它落定我就把上表补成逐族计算值。',
].join('\n');
