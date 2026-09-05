/**
 * 控制台预览：整轮工具流程在 UI 层会如何拆段 / 折叠 / 过滤旁白。
 *
 * 运行（在 gui/ 目录）：
 *   npm run preview:workflow
 *   npm run preview:workflow -- --live
 *   npm run preview:workflow -- --settled --one
 *   npm run preview:workflow -- --multi
 */

import {isProcessNarration} from '../src/lib/processNarration';
import {
	appendLiveThoughtStep,
	aggregateSteps,
	finalRoundProseMessageIds,
	formatCollapsedSegmentLabel,
	formatCursorToolParts,
	mergeTurnActivity,
	midRoundProseMessageIds,
	normalizeActivitySteps,
	segmentTurn,
	type ActivityStep,
	type TurnSegment,
} from '../src/lib/toolActivity';
import type {TurnItem} from '../src/lib/groupTranscript';
import {
	WORKFLOW_T0,
	buildMultiTurnWorkflowFixture,
	buildToolWorkflowFixture,
} from '../src/lib/toolWorkflowFixture';

function stepPreview(step: ActivityStep): string {
	if (step.verb === 'Thought') {
		return (step.thoughtContent || step.detail || '')
			.replace(/\s+/g, ' ')
			.slice(0, 72);
	}
	return (step.detail || step.verb).replace(/\s+/g, ' ').slice(0, 72);
}

const args = new Set(process.argv.slice(2));
const modeLive = args.has('--live');
const modeMulti = args.has('--multi');
const modeSettled = !modeLive;

function hr(title: string) {
	console.log(`\n══ ${title} ══`);
}

function sub(title: string) {
	console.log(`\n── ${title}`);
}

function printStep(step: ActivityStep, indent = '  ') {
	const flags = [
		step.running ? 'running' : null,
		step.error ? 'error' : null,
		step.diff ? `diff=+${step.diff.add}/-${step.diff.del}` : null,
	]
		.filter(Boolean)
		.join(' ');
	const preview =
		step.verb === 'Thought'
			? (step.thoughtContent || step.detail || '')
					.replace(/\s+/g, ' ')
					.slice(0, 72)
			: stepPreview(step);
	console.log(
		`${indent}▸ ${step.verb.padEnd(10)} ${preview}${flags ? `  [${flags}]` : ''}`,
	);
	if (step.verb !== 'Thought' && step.args) {
		const argsOne = step.args.replace(/\s+/g, ' ').slice(0, 90);
		console.log(
			`${indent}    args: ${argsOne}${step.args.length > 90 ? '…' : ''}`,
		);
	}
}

function printSegment(seg: TurnSegment, i: number, settled: boolean) {
	if (seg.kind === 'prose') {
		for (const m of seg.messages) {
			const narr = isProcessNarration(m.text);
			const hidden = settled && narr;
			const head = (m.text || '').replace(/\s+/g, ' ').slice(0, 80);
			console.log(
				`  [${i}] PROSE ${hidden ? '(收束隐藏旁白) ' : narr ? '(旁白·进行中可见) ' : ''}${JSON.stringify(head)}${m.text.length > 80 ? '…' : ''}`,
			);
		}
		return;
	}
	const label = formatCollapsedSegmentLabel(seg.steps, seg.summary);
	const cursor = formatCursorToolParts(seg.steps);
	console.log(`  [${i}] ACTIVITY 折叠头: "${label}"`);
	if (cursor.parts.length) {
		const diff =
			cursor.diffs.add || cursor.diffs.del
				? ` +${cursor.diffs.add} -${cursor.diffs.del}`
				: '';
		console.log(`       Cursor汇总(参考): ${cursor.parts.join(', ')}${diff}`);
	}
	console.log(`       展开后具体步骤 (${seg.steps.length}):`);
	for (const step of normalizeActivitySteps(
		seg.steps,
		seg.steps.some(s => s.running),
	)) {
		printStep(step, '         ');
	}
}

function simulateAssistantTurnView(items: TurnItem[], live: boolean) {
	hr(`模拟 AssistantTurn 展示  mode=${live ? 'LIVE 进行中' : 'SETTLED 已收束'}`);

	const segments = segmentTurn(items);
	sub(`segmentTurn → ${segments.length} 段（按 transcript 交错）`);

	segments.forEach((seg, i) => printSegment(seg, i, !live));

	const allToolSteps = segments
		.filter(
			(s): s is Extract<TurnSegment, {kind: 'activity'}> =>
				s.kind === 'activity',
		)
		.flatMap(s => s.steps.filter(st => st.verb !== 'Thought'));
	const allThoughts = segments
		.filter(
			(s): s is Extract<TurnSegment, {kind: 'activity'}> =>
				s.kind === 'activity',
		)
		.flatMap(s => s.steps.filter(st => st.verb === 'Thought'));

	sub('若合并全部工具为一条 Activity（曾试验的 Cursor 折叠）');
	if (allThoughts.length) {
		console.log(`  Thought 行数: ${allThoughts.length}`);
		allThoughts.forEach(s => printStep(s));
	}
	if (allToolSteps.length) {
		const agg = aggregateSteps(allToolSteps);
		const cursor = formatCursorToolParts(allToolSteps);
		console.log(`  折叠头 summary: ${agg.summary}`);
		console.log(`  Cursor parts:  ${cursor.parts.join(', ') || '(无)'}`);
		console.log(`  展开具体工具:`);
		allToolSteps.forEach(s => printStep(s));
	} else {
		console.log('  (无工具步骤)');
	}

	sub('旁白过滤 isProcessNarration');
	for (const seg of segments) {
		if (seg.kind !== 'prose') continue;
		for (const m of seg.messages) {
			const n = isProcessNarration(m.text);
			console.log(
				`  ${n ? '旁白' : '正文'}  ${JSON.stringify(m.text.slice(0, 60))}${m.text.length > 60 ? '…' : ''}`,
			);
		}
	}

	if (live) {
		sub('live Thought 追加（appendLiveThoughtStep）');
		const base = segments.flatMap(s =>
			s.kind === 'activity' ? s.steps : [],
		);
		const withLive = appendLiveThoughtStep(base, {
			active: true,
			since: WORKFLOW_T0 + 50,
			now: WORKFLOW_T0 + 4500,
			content:
				'继续读 ActivityLog，核对展开动画与具体工具行是否同时可见…',
		});
		const thoughts = withLive.filter(s => s.verb === 'Thought');
		console.log(`  Thought 行数（应≤去重后合理值）: ${thoughts.length}`);
		thoughts.forEach(s => printStep(s));
	}

	sub('当前默认 UI 口径（取消 Cursor 只显示汇总之后）');
	console.log('  · 按 segment 交错渲染');
	console.log('  · Activity 默认展开 → 看到 Read / Grepped / Edited 等具体行');
	console.log('  · settled 时隐藏旁白 prose');
	console.log('  · done on 展开层：合并步骤轨（无旁白）');
}

function simulateMultiTurnDoneOn() {
	hr('多轮 mergeTurnActivity / done on');
	const turns = buildMultiTurnWorkflowFixture().map(items => ({items}));
	const merged = mergeTurnActivity(turns, {
		startedAt: WORKFLOW_T0,
		endedAt: WORKFLOW_T0 + 60_000,
	});
	console.log(`  midRoundProse ids: ${[...midRoundProseMessageIds(turns)].join(',') || '(空)'}`);
	console.log(
		`  finalRoundProse ids: ${[...finalRoundProseMessageIds(turns)].join(',')}`,
	);
	if (!merged) {
		console.log('  (无合并 activity)');
		return;
	}
	console.log(`  summary: ${merged.summary}`);
	console.log(`  diffs: +${merged.diffs.add} -${merged.diffs.del}`);
	console.log(`  展开步骤 (${merged.steps.length}):`);
	for (const step of normalizeActivitySteps(merged.steps, false)) {
		printStep(step);
	}
}

function main() {
	console.log('XEYO 工具流程展示 — 控制台预览');
	console.log(`时间锚点: ${new Date(WORKFLOW_T0).toISOString()}`);
	console.log('fixture: src/lib/toolWorkflowFixture.ts');

	if (modeMulti) {
		simulateMultiTurnDoneOn();
	} else if (modeLive) {
		simulateAssistantTurnView(buildToolWorkflowFixture('live'), true);
	} else {
		simulateAssistantTurnView(buildToolWorkflowFixture('settled'), false);
	}

	if (!args.has('--one') && !modeMulti) {
		simulateAssistantTurnView(
			buildToolWorkflowFixture(modeSettled ? 'live' : 'settled'),
			modeSettled,
		);
		simulateMultiTurnDoneOn();
	}

	hr('用法');
	console.log('  npm run preview:workflow');
	console.log('  npm run preview:workflow -- --live');
	console.log('  npm run preview:workflow -- --settled --one');
	console.log('  npm run preview:workflow -- --multi');
	console.log('  npm test -- src/lib/toolWorkflowDisplay.test.ts');
	console.log('  npm test -- src/components/AssistantTurn.workflow.test.tsx');
	console.log('');
}

main();
