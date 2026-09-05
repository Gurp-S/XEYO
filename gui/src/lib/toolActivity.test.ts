import {describe, expect, it} from 'vitest';
import type {TurnItem} from './groupTranscript';
import {
	aggregateSteps,
	appendLiveThoughtStep,
	buildRoundActivityView,
	collectChangedFiles,
	collectLatestTodosFromItems,
	collectLatestTodosFromSteps,
	collectLiveSessionTodos,
	extractDiffFence,
	finalRoundProseMessageIds,
	formatCollapsedSegmentLabel,
	formatCursorToolParts,
	findHandoffStepId,
	formatDoneOn,
	injectThoughtSteps,
	isLiveTodoSnapshot,
	mergeTurnActivity,
	midRoundProseMessageIds,
	normalizeActivitySteps,
	parseTodosFromInput,
	parseTodosFromResult,
	roundHasIntermediateWork,
	segmentTurn,
	toolToStep,
} from './toolActivity';
import {oneLinePreview} from '../components/ActivityLog';

describe('toolToStep — Bash routed to dedicated tool (43 号)', () => {
	it('shows Bash → Read where the used tool would be shown, nothing else', () => {
		const step = toolToStep({
			id: 't1',
			name: 'Bash',
			input: JSON.stringify({command: 'cat a.py'}),
			result:
				'[routed: Bash cat → Read file_path="a.py"] Use Read directly — ' +
				'Bash is only for commands without a dedicated tool.\nhello\nworld',
			status: 'done',
			createdAt: 1,
		});
		expect(step.detail).toBe('Bash → Read');
		expect(step.verb).toBe('Ran');
	});

	it('plain Bash (no routed marker) keeps the command as detail', () => {
		const step = toolToStep({
			id: 't2',
			name: 'Bash',
			input: JSON.stringify({command: 'npm run build'}),
			result: 'compiled ok',
			status: 'done',
			createdAt: 2,
		});
		expect(step.detail).toBe('npm run build');
	});
});


describe('oneLinePreview — runtime tail never becomes the preview', () => {
	const HINT = '\n\n你正在用完全相同的参数重复调用同一个工具。不要重复执行：基于已有结果直接作答。';
	const NO_MATCH_TIP =
		'\n\nNo matches. If you expected matches, retry with -i (case-insensitive), or narrow the path/glob.';
	const SMALL_TIP =
		'\n\nTip: use output_mode="content" to see the matching lines directly instead of file names only.';

	it('grep row shows pattern, not no-match tip / repeat hint', () => {
		const step = toolToStep({
			id: 'g1',
			name: 'Grep',
			input: JSON.stringify({pattern: 'NO remote'}),
			result: `No matches found${NO_MATCH_TIP}${HINT}`,
			status: 'done',
			createdAt: 1,
		});
		expect(step.verb).toBe('Grepped');
		expect(oneLinePreview(step)).toBe('NO remote');
	});

	it('small-files tip line is filtered for glob rows', () => {
		const step = toolToStep({
			id: 'gl1',
			name: 'Glob',
			input: JSON.stringify({pattern: '**/*.tsx'}),
			result: `Found 1 file\nsidebar.tsx${SMALL_TIP}`,
			status: 'done',
			createdAt: 2,
		});
		expect(oneLinePreview(step)).toBe('**/*.tsx');
	});

	it('archived/zero-hit advisory tails stay invisible', () => {
		const step = toolToStep({
			id: 'r1',
			name: 'Grep',
			input: JSON.stringify({pattern: 'x'}),
			result:
				'prior result\n[elided Grep ab12cd34: old output] (archived; answer from remaining context)\n\n[提示] 这是本次任务中第 2 个不同查询的空结果。',
			status: 'done',
			createdAt: 3,
		});
		expect(oneLinePreview(step)).toBe('x');
	});

	it('sanitized fallback keeps first informative line when detail is empty', () => {
		const lines = (
			['', 'No matches found', 'worker output line 3'] as string[]
		).join('\n');
		expect(
			// biome-ignore lint:直接构造 detail 为空的边缘步骤
			oneLinePreview({
				id: 'z',
				verb: 'Ran' as const,
				detail: '',
				args: undefined,
				error: false,
				running: false,
				result: lines,
			}),
		).toBe('worker output line 3');
	});
});

describe('toolActivity', () => {
	it('maps file edit to Edited + basename', () => {
		const step = toolToStep({
			id: '1',
			name: 'FileEdit',
			input: JSON.stringify({file_path: 'D:/a/AssistantTurn.tsx'}),
			result: 'The file updated successfully. +2 -1',
			status: 'done',
			createdAt: 1,
		});
		expect(step.verb).toBe('Edited');
		expect(step.detail).toBe('AssistantTurn.tsx');
		expect(step.diff).toEqual({add: 2, del: 1});
	});

	it('collectChangedFiles aggregates edit paths and diffs', () => {
		const files = collectChangedFiles([
			{
				id: '1',
				verb: 'Edited',
				detail: 'a.ts',
				args: JSON.stringify({file_path: 'D:/proj/a.ts'}),
				result: 'ok +4 -1',
				diff: {add: 4, del: 1},
			},
			{
				id: '2',
				verb: 'Edited',
				detail: 'a.ts',
				args: JSON.stringify({file_path: 'D:/proj/a.ts'}),
				result: 'ok +2 -0',
				diff: {add: 2, del: 0},
			},
			{
				id: '3',
				verb: 'Read',
				detail: 'b.ts',
				result: 'x',
			},
		]);
		expect(files).toHaveLength(1);
		expect(files[0]).toMatchObject({name: 'a.ts', add: 6, del: 1});
	});

	it('collectChangedFiles includes Wrote and Created with new flag', () => {
		const createdResult = [
			'File created successfully at: D:/t/new.txt +1 -0',
			'',
			'```diff',
			'--- /dev/null',
			'+++ b/new.txt',
			'@@ -0,0 +1 @@',
			'+hello',
			'```',
		].join('\n');
		const files = collectChangedFiles([
			{
				id: '1',
				verb: 'Created',
				detail: 'new.txt',
				args: JSON.stringify({file_path: 'D:/t/new.txt', content: 'a'}),
				result: createdResult,
				diff: {add: 1, del: 0},
			},
			{
				id: '2',
				verb: 'Wrote',
				detail: 'old.txt',
				args: JSON.stringify({file_path: 'D:/t/old.txt', content: 'b'}),
				result: 'The file D:/t/old.txt has been updated successfully. +2 -1',
				diff: {add: 2, del: 1},
			},
		]);
		expect(files).toHaveLength(2);
		expect(files.find(f => f.name === 'new.txt')).toMatchObject({
			created: true,
			add: 1,
			del: 0,
		});
		expect(files.find(f => f.name === 'new.txt')?.diff).toContain('+hello');
		expect(files.find(f => f.name === 'old.txt')).toMatchObject({
			add: 2,
			del: 1,
		});
		expect(files.find(f => f.name === 'old.txt')?.created).toBeUndefined();
	});

	it('extractDiffFence pulls unified diff body', () => {
		const body = extractDiffFence(
			'ok +1 -0\n\n```diff\n+a\n-b\n```\n',
		);
		expect(body).toBe('+a\n-b');
	});

	it('estimates Write +/− from content args when result has no tag', () => {
		const step = toolToStep({
			id: 'w1',
			name: 'Write',
			input: JSON.stringify({
				file_path: 'D:/t/test tool.txt',
				content: 'a\nb\nc\n',
			}),
			result: 'File created successfully at: D:/t/test tool.txt',
			status: 'done',
			createdAt: 1,
		});
		expect(step.verb).toBe('Created');
		expect(step.diff).toEqual({add: 4, del: 0});
	});

	it('maps Write create vs update verbs', () => {
		expect(
			toolToStep({
				id: 'c1',
				name: 'Write',
				input: JSON.stringify({file_path: 'D:/a/out.txt', content: 'x'}),
				result: 'File created successfully at: D:/a/out.txt +1 -0',
				status: 'done',
				createdAt: 1,
			}).verb,
		).toBe('Created');
		expect(
			toolToStep({
				id: 'u1',
				name: 'Write',
				input: JSON.stringify({file_path: 'D:/a/out.txt', content: 'y'}),
				result:
					'The file D:/a/out.txt has been updated successfully. +1 -1',
				status: 'done',
				createdAt: 2,
			}).verb,
		).toBe('Wrote');
		expect(
			toolToStep({
				id: 'r1',
				name: 'Write',
				input: JSON.stringify({file_path: 'D:/a/out.txt', content: 'z'}),
				result: '',
				status: 'running',
				createdAt: 3,
			}).verb,
		).toBe('Writing');
	});

	it('clears running shimmer once a result body is present', () => {
		const step = toolToStep({
			id: 'r1',
			name: 'Read',
			input: '{"file_path":"D:/missing.txt"}',
			result: 'File does not exist',
			status: 'running',
			createdAt: 1,
		});
		expect(step.running).toBe(false);
		expect(step.verb).toBe('Read');
	});

	it('maps Read / Write / Edit tool names for activity UI', () => {
		expect(
			toolToStep({
				id: '1',
				name: 'Read',
				input: '{"file_path":"D:/a/pom.xml"}',
				result: 'ok',
				status: 'done',
				createdAt: 1,
			}).verb,
		).toBe('Read');
		expect(
			toolToStep({
				id: '2',
				name: 'Write',
				input: '{"file_path":"D:/a/out.txt","content":"x"}',
				result: 'File created successfully at: D:/a/out.txt',
				status: 'done',
				createdAt: 2,
			}).verb,
		).toBe('Created');
		expect(
			toolToStep({
				id: '3',
				name: 'Edit',
				input: '{"file_path":"D:/a/a.ts","old_string":"a","new_string":"b"}',
				result: 'ok',
				status: 'done',
				createdAt: 3,
			}).verb,
		).toBe('Edited');
	});

	it('summarizes Created / Wrote separately from Edited', () => {
		const items: TurnItem[] = [
			{
				kind: 'tool',
				tool: {
					id: 't1',
					name: 'Write',
					input: JSON.stringify({
						file_path: 'D:/a/new.ts',
						content: 'x',
					}),
					result: 'File created successfully at: D:/a/new.ts +1 -0',
					status: 'done',
					createdAt: 1,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 't2',
					name: 'Write',
					input: JSON.stringify({
						file_path: 'D:/a/old.ts',
						content: 'y',
					}),
					result:
						'The file D:/a/old.ts has been updated successfully. +1 -0',
					status: 'done',
					createdAt: 2,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 't3',
					name: 'Edit',
					input: JSON.stringify({
						file_path: 'D:/a/e.ts',
						old_string: 'a',
						new_string: 'b',
					}),
					result: 'ok +1 -1',
					status: 'done',
					createdAt: 3,
				},
			},
		];
		const segs = segmentTurn(items);
		expect(segs).toHaveLength(1);
		expect(segs[0]).toMatchObject({kind: 'activity'});
		if (segs[0]?.kind === 'activity') {
			expect(segs[0].summary).toMatch(/Created 1 file/i);
			expect(segs[0].summary).toMatch(/wrote 1 file/i);
			expect(segs[0].summary).toMatch(/edited 1 file/i);
		}
	});

	it('keeps assistant prose outside activity segments', () => {
		const items: TurnItem[] = [
			{
				kind: 'assistant',
				message: {
					id: 'a0',
					role: 'assistant',
					text: '当然！让我运行一下这些工具：',
					createdAt: 1,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 't1',
					name: 'echo',
					input: '{"text":"hi"}',
					result: 'hi',
					status: 'done',
					createdAt: 2,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 't2',
					name: 'Glob',
					input: '{"pattern":"**/*.txt"}',
					result: 'err',
					status: 'error',
					createdAt: 3,
				},
			},
			{
				kind: 'assistant',
				message: {
					id: 'a1',
					role: 'assistant',
					text: '工具测试结果：全部完成',
					createdAt: 4,
				},
			},
		];
		const segs = segmentTurn(items);
		expect(segs.map(s => s.kind)).toEqual(['prose', 'activity', 'prose']);
		expect(segs[0]).toMatchObject({
			kind: 'prose',
			messages: [{text: '当然！让我运行一下这些工具：'}],
		});
		expect(segs[1]).toMatchObject({
			kind: 'activity',
			summary: expect.stringMatching(/search|command/i),
		});
		expect(segs[2]).toMatchObject({
			kind: 'prose',
			messages: [{text: '工具测试结果：全部完成'}],
		});
	});

	it('adds expandable thought from assistant reasoningBefore', () => {
		const items: TurnItem[] = [
			{
				kind: 'assistant',
				message: {
					id: 'a1',
					role: 'assistant',
					text: '最终答案',
					reasoningBefore: '排查 gap 值',
					thoughtMs: 1200,
					createdAt: 4,
				},
			},
		];
		const segs = segmentTurn(items);
		expect(segs.map(s => s.kind)).toEqual(['activity', 'prose']);
		if (segs[0]?.kind === 'activity') {
			expect(segs[0].steps[0]?.thoughtContent).toBe('排查 gap 值');
		}
	});

	it('interleaves persisted isThought messages between tools', () => {
		const items: TurnItem[] = [
			{
				kind: 'tool',
				tool: {
					id: 't1',
					name: 'Grep',
					input: '{"pattern":"foo"}',
					result: 'ok',
					status: 'done',
					createdAt: 1,
				},
			},
			{
				kind: 'assistant',
				message: {
					id: 'th1',
					role: 'assistant',
					text: '排查 Sidebar gap',
					isThought: true,
					thoughtMs: 40_000,
					createdAt: 2,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 't2',
					name: 'Edit',
					input: '{"file_path":"Sidebar.tsx"}',
					result: 'ok',
					status: 'done',
					createdAt: 3,
				},
			},
		];
		const segs = segmentTurn(items);
		expect(segs).toHaveLength(1);
		if (segs[0]?.kind === 'activity') {
			expect(segs[0].steps.map(s => s.verb)).toEqual([
				'Grepped',
				'Thought',
				'Edited',
			]);
			expect(segs[0].steps[1]?.thoughtContent).toBe('排查 Sidebar gap');
		}
	});

	it('parseTodosFromInput reads TodoWrite payload', () => {
		const todos = parseTodosFromInput(
			JSON.stringify({
				todos: [
					{
						content: 'Run tests',
						status: 'in_progress',
						activeForm: 'Running tests',
					},
					{
						content: 'Ship',
						status: 'pending',
						activeForm: 'Shipping',
					},
				],
			}),
		);
		expect(todos).toHaveLength(2);
		expect(todos[0]).toMatchObject({
			content: 'Run tests',
			status: 'in_progress',
			activeForm: 'Running tests',
		});
	});

	it('parseTodosFromResult reads <todo_list> from tool_result', () => {
		const todos = parseTodosFromResult(
			`ok\n<todo_list>\n${JSON.stringify([
				{
					content: 'A',
					status: 'completed',
					activeForm: 'Doing A',
				},
				{
					content: 'B',
					status: 'in_progress',
					activeForm: 'Doing B',
				},
			])}\n</todo_list>`,
		);
		expect(todos).toHaveLength(2);
		expect(todos?.[0]?.status).toBe('completed');
		expect(todos?.[1]?.status).toBe('in_progress');
	});

	it('collectLatestTodosFromItems prefers settled <todo_list> over input', () => {
		const items: TurnItem[] = [
			{
				kind: 'tool',
				tool: {
					id: 't1',
					name: 'TodoWrite',
					input: JSON.stringify({
						todos: [
							{
								content: 'A',
								status: 'in_progress',
								activeForm: 'Doing A',
							},
							{
								content: 'B',
								status: 'pending',
								activeForm: 'Doing B',
							},
						],
					}),
					result: `ok\n<todo_list>\n${JSON.stringify([
						{
							content: 'A',
							status: 'completed',
							activeForm: 'Doing A',
						},
						{
							content: 'B',
							status: 'in_progress',
							activeForm: 'Doing B',
						},
					])}\n</todo_list>`,
					status: 'done',
					createdAt: 1,
				},
			},
		];
		const snap = collectLatestTodosFromItems(items);
		expect(snap?.todos[0]?.status).toBe('completed');
		expect(snap?.todos[1]?.status).toBe('in_progress');
		expect(isLiveTodoSnapshot(snap)).toBe(true);
	});

	it('toolToStep maps TodoWrite to Updating with task count', () => {
		const step = toolToStep({
			id: '1',
			name: 'TodoWrite',
			input: JSON.stringify({
				todos: [
					{
						content: 'A',
						status: 'pending',
						activeForm: 'Doing A',
					},
				],
			}),
			result: '',
			status: 'running',
			createdAt: 1,
		});
		expect(step.verb).toBe('Updating');
		expect(step.detail).toBe('1 task');
	});

	it('toolToStep maps WebSearch to Searched and Diagnostics to Diagnostics', () => {
		const search = toolToStep({
			id: 'w1',
			name: 'WebSearch',
			input: JSON.stringify({query: 'tailwind v4'}),
			result: 'provider: bing',
			status: 'done',
			createdAt: 1,
		});
		expect(search.verb).toBe('Searched');
		expect(search.detail).toBe('tailwind v4');

		const diag = toolToStep({
			id: 'd1',
			name: 'Diagnostics',
			input: JSON.stringify({path: 'src/a.ts'}),
			result: 'ok',
			status: 'done',
			createdAt: 2,
		});
		expect(diag.verb).toBe('Diagnostics');
		expect(diag.detail).toMatch(/a\.ts/);
		expect(diag.verb).not.toBe('Linted');
		expect(diag.verb).not.toBe('Grepped');
	});

	it('toolToStep maps Agent to Delegating / Delegated', () => {
		const running = toolToStep({
			id: 'a1',
			name: 'Agent',
			input: JSON.stringify({
				description: '调研权限策略',
				prompt: '详细任务…',
			}),
			result: '',
			status: 'running',
			createdAt: 1,
		});
		expect(running.verb).toBe('Delegating');
		expect(running.detail).toBe('调研权限策略');
		expect(running.running).toBe(true);
		expect(running.agent).toBe(true);

		const done = toolToStep({
			id: 'a2',
			name: 'Agent',
			input: JSON.stringify({description: '写总结'}),
			result: 'ok',
			status: 'done',
			createdAt: 2,
		});
		expect(done.verb).toBe('Delegated');
		expect(done.running).toBe(false);
		expect(done.agent).toBe(true);

		const failed = toolToStep({
			id: 'a3',
			name: 'Agent',
			input: JSON.stringify({description: '坏了'}),
			result: 'boom',
			status: 'error',
			createdAt: 3,
		});
		expect(failed.verb).toBe('Failed');
		expect(failed.agent).toBe(true);
		expect(failed.error).toBe(true);
	});

	it('collectLatestTodosFromItems keeps last TodoWrite snapshot', () => {
		const items: TurnItem[] = [
			{
				kind: 'tool',
				tool: {
					id: 't1',
					name: 'TodoWrite',
					input: JSON.stringify({
						todos: [
							{
								content: 'Old',
								status: 'completed',
								activeForm: 'Olding',
							},
						],
					}),
					result: 'ok',
					status: 'done',
					createdAt: 1,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 't2',
					name: 'TodoWrite',
					input: JSON.stringify({
						todos: [
							{
								content: 'New',
								status: 'in_progress',
								activeForm: 'Working',
							},
						],
					}),
					result: '',
					status: 'running',
					createdAt: 2,
				},
			},
		];
		const snap = collectLatestTodosFromItems(items);
		expect(snap?.id).toBe('t2');
		expect(snap?.running).toBe(true);
		expect(snap?.todos[0]?.content).toBe('New');
	});

	it('collectLatestTodosFromSteps reads activity segment steps', () => {
		const snap = collectLatestTodosFromSteps([
			{
				id: '1',
				verb: 'Updating',
				detail: '2 tasks',
				args: JSON.stringify({
					todos: [
						{
							content: 'One',
							status: 'pending',
							activeForm: 'Oneing',
						},
						{
							content: 'Two',
							status: 'completed',
							activeForm: 'Twoing',
						},
					],
				}),
				running: true,
			},
		]);
		expect(snap?.todos).toHaveLength(2);
		expect(snap?.running).toBe(true);
	});

	it('collectLiveSessionTodos hides when every item is completed', () => {
		const liveItems: TurnItem[] = [
			{
				kind: 'tool',
				tool: {
					id: 't1',
					name: 'TodoWrite',
					input: JSON.stringify({
						todos: [
							{
								content: 'A',
								status: 'completed',
								activeForm: 'Doing A',
							},
							{
								content: 'B',
								status: 'in_progress',
								activeForm: 'Doing B',
							},
						],
					}),
					result: 'ok',
					status: 'done',
					createdAt: 1,
				},
			},
		];
		const live = collectLiveSessionTodos(liveItems);
		expect(isLiveTodoSnapshot(live)).toBe(true);
		expect(live?.todos).toHaveLength(2);
		expect(live?.todos.find(t => t.status === 'completed')).toBeTruthy();

		const doneItems: TurnItem[] = [
			{
				kind: 'tool',
				tool: {
					id: 't2',
					name: 'TodoWrite',
					input: JSON.stringify({
						todos: [
							{
								content: 'A',
								status: 'completed',
								activeForm: 'Doing A',
							},
							{
								content: 'B',
								status: 'completed',
								activeForm: 'Doing B',
							},
						],
					}),
					result: 'ok',
					status: 'done',
					createdAt: 2,
				},
			},
		];
		expect(collectLiveSessionTodos(doneItems)).toBeNull();
	});
});

describe('aggregateSteps — 跨轮任务级汇总', () => {
	const step = (over: Partial<import('../lib/toolActivity').ActivityStep> & {id: string}) => ({
		verb: 'Grepped',
		detail: '',
		error: false,
		running: false,
		...over,
	});

	it('counts searches, reads, edits and dedups files across turns', () => {
		const {summary, diffs} = aggregateSteps([
			step({id: 'a', verb: 'Grepped', detail: 'NO remote'}),
			step({id: 'b', verb: 'Grepped', detail: 'space.id'}),
			step({id: 'c', verb: 'Read', detail: 'Sidebar.tsx'}),
			step({id: 'd', verb: 'Read', detail: 'Sidebar.tsx'}), // 同文件去重
			step({id: 'e', verb: 'Edited', detail: 'Sidebar.tsx', diff: {add: 3, del: 1}}),
			step({id: 'f', verb: 'Ran', detail: 'pnpm typecheck'}),
		]);
		expect(summary).toBe(
			'Edited 1 file, read 1 file, 2 searches, ran 1 command +3 -1',
		);
		expect(diffs).toEqual({add: 3, del: 1});
	});

	it('created-files and todo verbs map into the summary', () => {
		const {summary} = aggregateSteps([
			step({id: 'g', verb: 'Created', detail: 'new.ts'}),
			step({id: 'h', verb: 'Checked', detail: '3 tasks'}),
		]);
		expect(summary).toContain('Created 1 file');
		expect(summary).toContain('updated to-dos');
	});

	it('falls back to a generic count for unknown verbs', () => {
		const {summary} = aggregateSteps([
			step({id: 'i', verb: 'Called', detail: 'mcp.tool'}),
		]);
		expect(summary).toBe('ran 1 command');
	});

	it('empty input yields Working… placeholder', () => {
		expect(aggregateSteps([]).summary).toBe('Working…');
	});
});

describe('injectThoughtSteps', () => {
	const tool = (
		id: string,
		createdAt: number,
		extra?: Partial<import('./groupTranscript').ToolView>,
	): import('./groupTranscript').ToolView => ({
		id,
		name: 'Read',
		input: JSON.stringify({file_path: 'a.ts'}),
		result: 'ok',
		status: 'done',
		createdAt,
		...extra,
	});

	it('does not insert empty Thought rows from tool timestamps', () => {
		const tools = [tool('a', 1000), tool('b', 4500), tool('c', 5200)];
		const steps = injectThoughtSteps(tools.map(toolToStep), tools);
		expect(steps.map(s => s.verb)).toEqual(['Read', 'Read', 'Read']);
		expect(steps.every(s => s.verb !== 'Thought')).toBe(true);
	});

	it('uses reasoningBefore on tool when present', () => {
		const tools = [
			tool('a', 1000, {
				reasoningBefore: '排查 ActivityLog',
				thoughtMs: 1200,
			}),
		];
		const steps = injectThoughtSteps(tools.map(toolToStep), tools);
		expect(steps).toHaveLength(2);
		expect(steps[0]?.verb).toBe('Thought');
		expect(steps[0]?.thoughtContent).toBe('排查 ActivityLog');
		expect(steps[0]?.detail).toBe('briefly');
	});

	it('appendLiveThoughtStep adds running thought with content', () => {
		const out = appendLiveThoughtStep([], {
			active: true,
			since: Date.now() - 500,
			now: Date.now(),
			content: 'live reasoning',
		});
		expect(out).toHaveLength(1);
		expect(out[0]?.verb).toBe('Thought');
		expect(out[0]?.running).toBe(true);
		expect(out[0]?.thoughtContent).toBe('live reasoning');
	});

	it('appendLiveThoughtStep updates existing live thought', () => {
		const first = appendLiveThoughtStep([], {
			active: true,
			since: Date.now() - 500,
			now: Date.now(),
			content: 'a',
		});
		const second = appendLiveThoughtStep(first, {
			active: true,
			since: Date.now() - 800,
			now: Date.now(),
			content: 'ab',
		});
		expect(second).toHaveLength(1);
		expect(second[0]?.thoughtContent).toBe('ab');
	});

	it('appendLiveThoughtStep clears running on prior thought rows', () => {
		const prior = [
			{id: 't1', verb: 'Grepped', detail: 'foo', running: false},
			{id: 'old-thought', verb: 'Thought', detail: '1s', running: true},
		];
		const out = appendLiveThoughtStep(prior, {
			active: true,
			since: Date.now() - 500,
			now: Date.now(),
			content: '续写',
		});
		expect(out).toHaveLength(2);
		expect(out[0]?.running).toBe(false);
		expect(out.at(-1)?.id).toBe('old-thought');
		expect(out.at(-1)?.running).toBe(true);
		expect(out.at(-1)?.thoughtContent).toBe('续写');
	});

	it('appendLiveThoughtStep revives trailing Thought instead of stacking Thinking', () => {
		const prior = [
			{id: 'read', verb: 'Read', detail: 'a.ts', running: false},
			{
				id: 'thought-1',
				verb: 'Thought',
				detail: 'briefly',
				thoughtContent: '从 package 看',
				running: false,
			},
		];
		const out = appendLiveThoughtStep(prior, {
			active: true,
			since: Date.now() - 4000,
			now: Date.now(),
			content: '从 package 看更多',
		});
		expect(out.filter(s => s.verb === 'Thought')).toHaveLength(1);
		expect(out.at(-1)?.running).toBe(true);
		expect(out.at(-1)?.id).toBe('thought-1');
		expect(out.at(-1)?.thoughtContent).toBe('从 package 看更多');
	});
});

describe('normalizeActivitySteps', () => {
	it('keeps only the last running step when active', () => {
		const steps = normalizeActivitySteps(
			[
				{id: 'a', verb: 'Grepped', detail: 'x', running: true},
				{id: 'b', verb: 'Thought', detail: 'briefly', running: true},
			],
			true,
		);
		expect(steps[0]?.running).toBe(false);
		expect(steps[1]?.running).toBe(true);
	});

	it('clears all running when inactive', () => {
		const steps = normalizeActivitySteps(
			[{id: 'a', verb: 'Grepping', detail: 'x', running: true}],
			false,
		);
		expect(steps[0]?.running).toBe(false);
	});
});

describe('round collapse helpers', () => {
	it('finalRoundProseMessageIds keeps only the last assistant prose', () => {
		const turns = [
			{
				items: [
					{
						kind: 'assistant' as const,
						message: {
							id: 'a1',
							role: 'assistant' as const,
							text: '中间说明',
							createdAt: 1,
						},
					},
					{
						kind: 'tool' as const,
						tool: {
							id: 't1',
							name: 'Grep',
							input: '{}',
							result: 'ok',
							status: 'done' as const,
							createdAt: 2,
						},
					},
					{
						kind: 'assistant' as const,
						message: {
							id: 'a2',
							role: 'assistant' as const,
							text: '最终答案',
							createdAt: 3,
						},
					},
				],
			},
		];
		expect(finalRoundProseMessageIds(turns)).toEqual(new Set(['a2']));
		expect(roundHasIntermediateWork(turns)).toBe(true);
	});

	it('midRoundProseMessageIds hides all mid prose when settled', () => {
		const turns = [
			{
				items: [
					{
						kind: 'assistant' as const,
						message: {
							id: 'n1',
							role: 'assistant' as const,
							text: '让我查看工作区相关组件:',
							createdAt: 1,
						},
					},
					{
						kind: 'tool' as const,
						tool: {
							id: 't1',
							name: 'Grep',
							input: '{}',
							result: 'ok',
							status: 'done' as const,
							createdAt: 2,
						},
					},
					{
						kind: 'assistant' as const,
						message: {
							id: 'a2',
							role: 'assistant' as const,
							text: '最终答案',
							createdAt: 3,
						},
					},
				],
			},
		];
		expect(midRoundProseMessageIds(turns).size).toBe(0);
	});
});

describe('buildRoundActivityView', () => {
	const toolItem = (id: string, name: string, detail: string): TurnItem => ({
		kind: 'tool',
		tool: {
			id,
			name,
			input:
				name === 'Grep'
					? JSON.stringify({pattern: detail})
					: JSON.stringify({file_path: detail}),
			result: 'ok',
			status: 'done',
			createdAt: 1000,
		},
	});
	const proseItem = (id: string, text: string): TurnItem => ({
		kind: 'assistant',
		message: {id, role: 'assistant', text, createdAt: 2000},
	});

	it('shows aggregate summary while round is live', () => {
		const view = buildRoundActivityView(
			[{items: [toolItem('t1', 'Grep', 'foo'), toolItem('t2', 'Read', 'a.ts')]}],
			{
				taskFinalAnswerDone: false,
				roundLive: true,
			},
		);
		expect(view?.active).toBe(true);
		expect(view?.summary).toMatch(/Read 1 file/);
	});

	it('collapses to done on when final prose turn completes', () => {
		const view = buildRoundActivityView(
			[
				{items: [toolItem('t1', 'Grep', 'foo')]},
				{items: [proseItem('p1', '完成。')]},
			],
			{
				startedAt: 0,
				endedAt: 1_725_000_000_000,
				taskFinalAnswerDone: true,
				roundLive: false,
			},
		);
		expect(view?.active).toBe(false);
		expect(view?.summary.startsWith('done on ')).toBe(true);
	});

	it('appends live thought when idle between tools', () => {
		const view = buildRoundActivityView([{items: [toolItem('t1', 'Grep', 'foo')]}], {
			taskFinalAnswerDone: false,
			roundLive: true,
			liveThought: {since: Date.now() - 500, content: '排查中'},
		});
		expect(view?.steps.at(-1)?.verb).toBe('Thought');
		expect(view?.steps.at(-1)?.thoughtContent).toBe('排查中');
	});

	it('does not duplicate live thought when thought-stream is already persisted', () => {
		const items: TurnItem[] = [
			{
				kind: 'assistant',
				message: {
					id: 'thought-stream-s1',
					role: 'assistant',
					text: '查找 No remote 相关代码',
					isThought: true,
					thoughtMs: 4000,
					createdAt: 500,
				},
			},
			{
				kind: 'tool',
				tool: {
					id: 't1',
					name: 'Grep',
					input: '{"pattern":"No remote"}',
					result: 'ok',
					status: 'done',
					createdAt: 1000,
				},
			},
		];
		const view = buildRoundActivityView([{items}], {
			taskFinalAnswerDone: false,
			roundLive: true,
			liveThought: {
				since: Date.now() - 4000,
				content: '查找 No remote 相关代码',
			},
		});
		const thoughts = view?.steps.filter(s => s.verb === 'Thought') ?? [];
		expect(thoughts).toHaveLength(1);
		expect(thoughts[0]?.id).toBe('thought-stream-s1');
		expect(thoughts[0]?.running).toBe(true);
	});
});

describe('mergeTurnActivity — 任务收尾单层聚合', () => {
	const toolItem = (id: string, name: string, detail: string): TurnItem => ({
		kind: 'tool',
		tool: {
			id,
			name,
			input:
				name === 'Grep'
					? JSON.stringify({pattern: detail})
					: JSON.stringify({file_path: detail}),
			result: 'ok',
			status: 'done',
			createdAt: 1,
		},
	});
	const proseItem = (id: string, text: string): TurnItem => ({
		kind: 'assistant',
		message: {id, role: 'assistant', text, createdAt: 2},
	});

	it('unions steps across turns in order and summarizes with done on', () => {
		const merged = mergeTurnActivity([
			{items: [proseItem('p1', '我先看看。'), toolItem('t1', 'Grep', 'foo')]},
			{
				items: [
					proseItem('p2', '再看一处。'),
					toolItem('t2', 'Grep', 'bar'),
					toolItem('t3', 'Read', 'a.ts'),
					proseItem('p3', '完成。'),
				],
			},
			// 纯文本收尾轮：无工具，不贡献步骤
			{items: [proseItem('p4', '最终答案。')]},
		], {startedAt: 0, endedAt: 1_725_000_000_000});
		expect(merged).not.toBeNull();
		expect(merged!.steps.map(s => s.detail)).toEqual(['foo', 'bar', 'a.ts']);
		expect(merged!.summary.startsWith('done on ')).toBe(true);
		expect(merged!.diffs).toEqual({add: 0, del: 0});
	});

	it('returns null when no turn contributed tools', () => {
		expect(
			mergeTurnActivity([{items: [proseItem('p1', 'hi')]}]),
		).toBeNull();
	});

	it('uses last item createdAt as done on time (not wall clock)', () => {
		const endMs = Date.UTC(2026, 7, 28, 10, 15, 0); // Aug 28, 2026
		const merged = mergeTurnActivity([
			{
				items: [
					{
						kind: 'tool',
						tool: {
							id: 't1',
							name: 'Read',
							input: JSON.stringify({file_path: 'a.ts'}),
							result: 'ok',
							status: 'done',
							createdAt: endMs - 5_000,
						},
					},
					{
						kind: 'assistant',
						message: {
							id: 'p1',
							role: 'assistant',
							text: '完成。',
							createdAt: endMs,
						},
					},
				],
			},
		]);
		expect(merged).not.toBeNull();
		expect(merged!.summary).toBe(formatDoneOn(endMs));
		// 再次合并应稳定，不随墙钟漂移
		const again = mergeTurnActivity([
			{
				items: [
					{
						kind: 'tool',
						tool: {
							id: 't1',
							name: 'Read',
							input: JSON.stringify({file_path: 'a.ts'}),
							result: 'ok',
							status: 'done',
							createdAt: endMs - 5_000,
						},
					},
					{
						kind: 'assistant',
						message: {
							id: 'p1',
							role: 'assistant',
							text: '完成。',
							createdAt: endMs,
						},
					},
				],
			},
		]);
		expect(again!.summary).toBe(merged!.summary);
	});
});

describe('formatCollapsedSegmentLabel', () => {
	it('uses Thought briefly / Thought Ns for thought-only segments', () => {
		expect(
			formatCollapsedSegmentLabel(
				[{id: 't', verb: 'Thought', detail: 'briefly', running: false}],
				'Working…',
			),
		).toBe('Thought briefly');
		expect(
			formatCollapsedSegmentLabel(
				[{id: 't', verb: 'Thought', detail: '12s', running: false}],
				'Working…',
			),
		).toBe('Thought 12s');
	});

	it('uses N steps instead of Explored aggregate for tool segments', () => {
		expect(
			formatCollapsedSegmentLabel(
				[{id: 'r', verb: 'Read', detail: 'a.ts', running: false}],
				'Explored 13 files, 16 searches +44 -2',
			),
		).toBe('1 step');
		expect(
			formatCollapsedSegmentLabel(
				[
					{id: 'r', verb: 'Read', detail: 'a.ts', running: false},
					{id: 'g', verb: 'Grepped', detail: 'foo', running: false},
				],
				'Explored 1 file, 1 search',
			),
		).toBe('2 steps');
	});
});

describe('findHandoffStepId', () => {
	it('matches basename in thought token to next tool detail', () => {
		const steps = [
			{id: 'th', verb: 'Thought', detail: '4s', running: true},
			{
				id: 'r1',
				verb: 'Reading',
				detail: 'gui/src/components/TitleBar.tsx',
				running: true,
			},
			{id: 'g1', verb: 'Grepped', detail: 'SquareStack', running: false},
		];
		expect(
			findHandoffStepId('现在查看 TitleBar.tsx 的实现', steps),
		).toBe('r1');
	});

	it('matches identifier / CJK needles in thought token to tool detail', () => {
		expect(
			findHandoffStepId('继续 Grep SquareStack 图标', [
				{id: 'th', verb: 'Thought', detail: '2s', running: true},
				{
					id: 'g1',
					verb: 'Grepped',
					detail: 'SquareStack',
					running: false,
				},
			]),
		).toBe('g1');
		expect(
			findHandoffStepId('先打开起步阶段评测结果再清空', [
				{id: 'th', verb: 'Thought', detail: '1s', running: false},
				{
					id: 'r1',
					verb: 'Read',
					detail: '起步阶段评测结果.md',
					running: true,
				},
			]),
		).toBe('r1');
	});
});

describe('formatCursorToolParts', () => {
	it('builds categorized label with lowercase follow-ons', () => {
		const {parts, diffs} = formatCursorToolParts([
			{id: 'e1', verb: 'Edited', detail: 'a.ts', diff: {add: 10, del: 2}},
			{id: 'e2', verb: 'Edited', detail: 'b.ts', diff: {add: 5, del: 1}},
			{id: 'r1', verb: 'Read', detail: 'c.ts'},
			{id: 'g1', verb: 'Grepped', detail: 'foo'},
			{id: 's1', verb: 'Ran', detail: 'npm test'},
		]);
		expect(parts.join(', ')).toBe(
			'Edited 2 files, read 1 file, 1 search, ran 1 command',
		);
		expect(diffs).toEqual({add: 15, del: 3});
	});
});
