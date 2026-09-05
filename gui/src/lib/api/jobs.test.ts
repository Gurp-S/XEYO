/**
 * jobs.test.ts — 42 号 jobs API 纯函数单测。
 *
 * 覆盖：归一化防御（坏行跳过 / 非数组空集）、弹层确定性排序
 * （活跃 startedAt 升序在前、终态 finishedAt 降序在后）、角标计数。
 */
import {describe, expect, it} from 'vitest';
import {
	activeJobsCount,
	normalizeJobSnapshots,
	sortJobsForPanel,
	type JobSnapshot,
} from './jobs';

function job(over: Partial<JobSnapshot>): JobSnapshot {
	return {
		job_id: 'bash-1',
		kind: 'bash',
		label: '全量回归',
		status: 'running',
		detail: '',
		reported: false,
		started_at: 1000,
		finished_at: 0,
		...over,
	};
}

describe('normalizeJobSnapshots', () => {
	it('非数组 → 空集', () => {
		expect(normalizeJobSnapshots(null)).toEqual([]);
		expect(normalizeJobSnapshots('x')).toEqual([]);
	});

	it('逐条防御：坏行跳过、合法行保留', () => {
		const out = normalizeJobSnapshots([
			job({job_id: 'bash-1'}),
			{job_id: '', status: 'running'},
			'garbage',
			job({job_id: 'bash-2', status: 'succeeded'}),
		]);
		expect(out.map(j => j.job_id)).toEqual(['bash-1', 'bash-2']);
	});
});

describe('sortJobsForPanel', () => {
	it('活跃行在前（startedAt 升序），终态行在后（finishedAt 降序）', () => {
		const rows = sortJobsForPanel([
			job({job_id: 'done-old', status: 'succeeded', started_at: 100, finished_at: 200}),
			job({job_id: 'run-2', status: 'running', started_at: 500}),
			job({job_id: 'done-new', status: 'failed', started_at: 150, finished_at: 900}),
			job({job_id: 'run-1', status: 'running', started_at: 400}),
			job({job_id: 'stop', status: 'stopping', started_at: 450}),
		]);
		expect(rows.map(j => j.job_id)).toEqual([
			'run-1',
			'run-2',
			'stop',
			'done-new',
			'done-old',
		]);
	});

	it('不改动入参（拷贝排序）', () => {
		const rows = [
			job({job_id: 'b', status: 'succeeded', started_at: 1, finished_at: 2}),
			job({job_id: 'a', status: 'running', started_at: 3}),
		];
		sortJobsForPanel(rows);
		expect(rows.map(j => j.job_id)).toEqual(['b', 'a']);
	});
});

describe('activeJobsCount', () => {
	it('只计 running + stopping', () => {
		expect(
			activeJobsCount([
				job({status: 'running'}),
				job({status: 'stopping'}),
				job({status: 'succeeded'}),
				job({status: 'failed'}),
			]),
		).toBe(2);
	});
});
