/**
 * 工具流程展示 — 详细回归测试。
 *
 * 覆盖：
 * - segmentTurn 交错拆段（Thought / 旁白 / 多类工具 / 结论）
 * - toolToStep 动词与 detail（Grep/Read/Glob/Edit/Write/Bash/Todo/error）
 * - 旁白识别与 settled 隐藏口径
 * - appendLiveThoughtStep 不叠双 Thought/Thinking
 * - mergeTurnActivity / midRoundProse / finalRoundProse（done on）
 * - 展开后具体工具行仍在（非只显示 Explored N files）
 */

import {describe, expect, it} from 'vitest';
import {isProcessNarration} from './processNarration';
import {oneLinePreview} from '../components/ActivityLog';
import {
	appendLiveThoughtStep,
	aggregateSteps,
	finalRoundProseMessageIds,
	formatCollapsedSegmentLabel,
	mergeTurnActivity,
	midRoundProseMessageIds,
	normalizeActivitySteps,
	segmentTurn,
	toolToStep,
	type ActivityStep,
} from './toolActivity';
import {
	WORKFLOW_T0,
	buildMultiTurnWorkflowFixture,
	buildToolWorkflowFixture,
} from './toolWorkflowFixture';

function flatActivitySteps(
	items: ReturnType<typeof buildToolWorkflowFixture>,
): ActivityStep[] {
	return segmentTurn(items).flatMap(seg =>
		seg.kind === 'activity' ? seg.steps : [],
	);
}

function toolStepsOnly(steps: ActivityStep[]): ActivityStep[] {
	return steps.filter(s => s.verb !== 'Thought');
}

describe('tool workflow display — fixture integrity', () => {
	it('settled fixture contains thought, narrations, tools, and final answer', () => {
		const items = buildToolWorkflowFixture('settled');
		const kinds = items.map(i =>
			i.kind === 'tool' ? `tool:${i.tool.name}` : `asst:${i.message.id}`,
		);
		expect(kinds).toContain('asst:thought-1');
		expect(kinds).toContain('asst:narration-1');
		expect(kinds).toContain('tool:Grep');
		expect(kinds).toContain('tool:Read');
		expect(kinds).toContain('tool:Glob');
		expect(kinds).toContain('tool:Edit');
		expect(kinds).toContain('tool:Write');
		expect(kinds).toContain('tool:TodoWrite');
		expect(kinds).toContain('tool:Bash');
		expect(kinds).toContain('asst:final-1');
		expect(items.some(i => i.kind === 'tool' && i.tool.status === 'error')).toBe(
			true,
		);
	});

	it('live fixture ends with a running Read and no final prose', () => {
		const items = buildToolWorkflowFixture('live');
		const last = items.at(-1);
		expect(last?.kind).toBe('tool');
		if (last?.kind === 'tool') {
			expect(last.tool.status).toBe('running');
			expect(last.tool.name).toBe('Read');
		}
		expect(
			items.some(i => i.kind === 'assistant' && i.message.id === 'final-1'),
		).toBe(false);
	});
});

describe('tool workflow display — segmentTurn interleaving', () => {
	it('keeps transcript order: thought → narration → tools → final', () => {
		const segs = segmentTurn(buildToolWorkflowFixture('settled'));
		expect(segs.length).toBeGreaterThan(4);

		const outline = segs.map(seg => {
			if (seg.kind === 'prose') {
				return `prose:${seg.messages.map(m => m.id).join(',')}`;
			}
			const verbs = seg.steps.map(s => s.verb).join('|');
			return `act:${verbs}`;
		});

		// 首段应为 Thought（isThought 消息）
		expect(outline[0]).toMatch(/^act:Thought/);
		// 含旁白 prose
		expect(outline.some(o => o.includes('narration-1'))).toBe(true);
		// 含最终结论
		expect(outline.at(-1)).toMatch(/final-1/);
		// 中间有具体工具动词，不是空 activity
		expect(
			outline.some(
				o =>
					o.includes('Grepped') ||
					o.includes('Read') ||
					o.includes('Edited'),
			),
		).toBe(true);
	});

	it('each activity segment expands to concrete tool rows (not only summary)', () => {
		const segs = segmentTurn(buildToolWorkflowFixture('settled'));
		const activity = segs.filter(s => s.kind === 'activity');
		expect(activity.length).toBeGreaterThan(0);

		for (const seg of activity) {
			if (seg.kind !== 'activity') continue;
			const tools = toolStepsOnly(seg.steps);
			if (tools.length === 0) continue;
			const label = formatCollapsedSegmentLabel(seg.steps, seg.summary);
			// 折叠头可以是汇总，但步骤列表必须有具体 verb+detail
			expect(seg.steps.length).toBeGreaterThan(0);
			for (const step of tools) {
				expect(step.verb).toBeTruthy();
				expect(step.detail || step.args).toBeTruthy();
				expect(oneLinePreview(step).length).toBeGreaterThan(0);
			}
			expect(label.length).toBeGreaterThan(0);
		}
	});
});

describe('tool workflow display — toolToStep verbs', () => {
	it('maps every tool in the fixture to the expected verb family', () => {
		const items = buildToolWorkflowFixture('settled');
		const tools = items.filter(i => i.kind === 'tool').map(i => i.tool);
		const byId = Object.fromEntries(
			tools.map(t => [t.id, toolToStep(t)]),
		);

		expect(byId['grep-1']?.verb).toBe('Grepped');
		expect(byId['grep-1']?.detail).toMatch(/maximize|SquareStack/);
		expect(byId['read-1']?.verb).toBe('Read');
		expect(byId['read-1']?.detail).toMatch(/TitleBar/);
		expect(byId['glob-1']?.verb).toBe('Globbed');
		expect(byId['write-1']?.verb).toBe('Created');
		expect(byId['edit-1']?.verb).toBe('Edited');
		expect(byId['edit-1']?.diff?.add).toBeGreaterThan(0);
		expect(byId['todo-1']?.verb).toBe('Checked');
		expect(byId['bash-1']?.verb).toBe('Ran');
		expect(byId['fail-1']?.verb).toBe('Ran');
		expect(byId['fail-1']?.error).toBe(true);
	});

	it('running tool becomes Reading with running flag', () => {
		const items = buildToolWorkflowFixture('live');
		const live = items.find(
			i => i.kind === 'tool' && i.tool.id === 'read-live',
		);
		expect(live?.kind).toBe('tool');
		if (live?.kind !== 'tool') return;
		const step = toolToStep(live.tool);
		expect(step.verb).toBe('Reading');
		expect(step.running).toBe(true);
	});
});

describe('tool workflow display — narration filter', () => {
	it('flags mid-workflow旁白 and keeps final answer', () => {
		expect(
			isProcessNarration(
				'我来帮你找到XEYO项目中最小化和最大化按钮的图标位置。让我先搜索相关的代码文件...',
			),
		).toBe(true);
		expect(isProcessNarration('现在让我查看 TitleBar.tsx 的具体实现：')).toBe(
			true,
		);
		expect(
			isProcessNarration(
				'根据代码分析，我找到了XEYO项目中最小化和最大化按钮的图标位置：\n\n## 最小化按钮',
			),
		).toBe(false);
	});

	it('settled view hides narration prose ids from mid round set', () => {
		const turns = buildMultiTurnWorkflowFixture().map(items => ({items}));
		// midRound 当前口径：收尾展开层不展示中间 prose
		expect(midRoundProseMessageIds(turns).size).toBe(0);
		const finals = finalRoundProseMessageIds(turns);
		expect(finals.has('final-t2')).toBe(true);
		expect(finals.has('narration-1')).toBe(false);
	});
});

describe('tool workflow display — Thought dedupe', () => {
	it('does not stack Thinking on an existing trailing Thought', () => {
		const steps = flatActivitySteps(buildToolWorkflowFixture('settled'));
		const withThought = steps.filter(
			s => s.verb === 'Thought' || s.verb === 'Grepped',
		);
		// 取到第一个 Thought 为止的前缀，再追加 live
		const idx = withThought.findIndex(s => s.verb === 'Thought');
		expect(idx).toBeGreaterThanOrEqual(0);
		const prefix = withThought.slice(0, idx + 1).map(s => ({
			...s,
			running: false as const,
		}));
		const out = appendLiveThoughtStep(prefix, {
			active: true,
			since: WORKFLOW_T0,
			now: WORKFLOW_T0 + 4000,
			content: '继续核对 SquareStack 是否已 import',
		});
		expect(out.filter(s => s.verb === 'Thought')).toHaveLength(1);
		expect(out.at(-1)?.running).toBe(true);
		expect(out.at(-1)?.thoughtContent).toContain('SquareStack');
	});
});

describe('tool workflow display — done on merge', () => {
	it('mergeTurnActivity unions tools across turns with concrete steps', () => {
		const turns = buildMultiTurnWorkflowFixture().map(items => ({items}));
		const merged = mergeTurnActivity(turns, {
			startedAt: WORKFLOW_T0,
			endedAt: WORKFLOW_T0 + 60_000,
		});
		expect(merged).not.toBeNull();
		expect(merged!.summary.startsWith('done on ')).toBe(true);

		const tools = toolStepsOnly(merged!.steps);
		const verbs = new Set(tools.map(s => s.verb));
		expect(verbs.has('Grepped') || verbs.has('Read')).toBe(true);
		expect(tools.some(s => /TitleBar|package\.json|SquareStack/i.test(s.detail))).toBe(
			true,
		);
		// 汇总可存在，但步骤轨必须多于「一条假汇总」
		expect(tools.length).toBeGreaterThan(3);
	});

	it('normalizeActivitySteps keeps only one running step when live', () => {
		const steps = flatActivitySteps(buildToolWorkflowFixture('live'));
		const normalized = normalizeActivitySteps(steps, true);
		const running = normalized.filter(s => s.running);
		expect(running.length).toBeLessThanOrEqual(1);
		if (running[0]) {
			expect(running[0].verb).toMatch(/Reading|Thought/);
		}
	});
});

describe('tool workflow display — aggregate vs concrete rows', () => {
	it('aggregate summary exists but never replaces per-tool details', () => {
		const tools = toolStepsOnly(
			flatActivitySteps(buildToolWorkflowFixture('settled')),
		);
		const {summary, diffs} = aggregateSteps(tools);
		expect(summary.length).toBeGreaterThan(0);
		// 具体行：每条都有可读 preview
		const previews = tools.map(s => `${s.verb} ${oneLinePreview(s)}`);
		expect(previews.some(p => /Grepped/.test(p))).toBe(true);
		expect(previews.some(p => /Read/.test(p))).toBe(true);
		expect(previews.some(p => /Edited|Wrote|Created/.test(p))).toBe(true);
		expect(previews.some(p => /Ran/.test(p))).toBe(true);
		// diff 来自 Edit
		expect(diffs.add + diffs.del).toBeGreaterThan(0);
	});
});
