/**
 * SessionJobsBadge.test.tsx — 42 号 P0 GUI 单测。
 *
 * 覆盖（42 号 §12 GUI 部分）：
 * - 角标零隐藏：无任务整个不渲染（会长控件禁止）。
 * - 角标计数：running+stopping 计数 + 总数（`后台 1/2`）。
 * - 弹层：活跃行在前；detail 有则取代状态词；终态行弱化保留；耗时冻结。
 * - 空集 = 删除键：GET 返回空后 store 键被删除、控件消失。
 */
import {cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {useChatStore} from '@/stores/chatStore';
import {SessionJobsBadge} from './SessionJobsBadge';
import type {JobSnapshot} from '@/lib/api/jobs';

const fetchSessionJobsMock = vi.fn();

vi.mock('@/lib/api/jobs', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api/jobs')>();
	return {
		...actual,
		fetchSessionJobs: (...args: unknown[]) =>
			fetchSessionJobsMock(...args),
	};
});

function job(over: Partial<JobSnapshot>): JobSnapshot {
	return {
		job_id: 'bash-1',
		kind: 'bash',
		label: '全量回归',
		status: 'running',
		detail: '',
		reported: false,
		started_at: Date.now() - 65_000,
		finished_at: 0,
		...over,
	};
}

function seed(sessionId: string, jobs: JobSnapshot[]) {
	fixtureJobs = jobs;
	useChatStore.setState(s => {
		const next = {...s.sessionJobsById};
		if (jobs.length === 0) {
			delete next[sessionId];
		} else {
			next[sessionId] = jobs;
		}
		return {activeId: sessionId, sessionJobsById: next};
	});
}

/** GET 轮询 mock 的 fixture（照 SessionGoalDock.test 模式）：返回当前 seed，
 *  防 mount 轮询的 writeJobs([]) 按「空集=删除键」把刚 seed 的数据抹掉。 */
let fixtureJobs: JobSnapshot[] | null = null;

beforeEach(() => {
	fetchSessionJobsMock.mockReset();
	fetchSessionJobsMock.mockImplementation(async () => ({
		jobs: fixtureJobs ?? [],
		version: 0,
	}));
	fixtureJobs = null;
	useChatStore.setState({activeId: 's1', sessionJobsById: {}});
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe('SessionJobsBadge', () => {
	it('无任务整个不渲染（角标零隐藏）', () => {
		const {container} = render(<SessionJobsBadge sessionId="s1" />);
		expect(container).toBeEmptyDOMElement();
	});

	it('角标计数 = 进行中/总数', () => {
		seed('s1', [
			job({job_id: 'bash-1', status: 'running'}),
			job({job_id: 'bash-2', status: 'succeeded', finished_at: Date.now()}),
		]);
		render(<SessionJobsBadge sessionId="s1" />);
		expect(screen.getByText('后台 1/2')).toBeInTheDocument();
	});

	it('弹层：活跃行在前、detail 取代状态词、终态弱化、耗时冻结', async () => {
		const t0 = Date.now();
		seed('s1', [
			job({
				job_id: 'bash-2',
				label: '旧任务',
				status: 'succeeded',
				started_at: t0 - 125_000,
				finished_at: t0 - 5_000,
			}),
			job({
				job_id: 'bash-3',
				label: '新任务',
				status: 'failed',
				detail: 'exit code 1',
				started_at: t0 - 1_000,
				finished_at: t0,
			}),
			job({job_id: 'bash-1', label: '全量回归', status: 'running'}),
		]);
		render(<SessionJobsBadge sessionId="s1" />);
		await userEvent.setup().click(screen.getByRole('button'));
		const region = await screen.findByRole('region', {name: '后台任务'});
		// 活跃行在前：bash-1 的行（label 全量回归）出现在最前。
		const rows = Array.from(region.querySelectorAll('li'));
		expect(rows[0].textContent).toContain('bash-1');
		// detail 有则取代状态词：failed 行显示 exit code 1，不显示「失败」。
		const failedRow = rows.find(r => r.textContent?.includes('bash-3'));
		expect(failedRow?.textContent).toContain('exit code 1');
		expect(failedRow?.textContent).not.toContain('失败');
		// 终态耗时冻结：succeeded 行 = finishedAt - startedAt = 120s（02:00）。
		const doneRow = rows.find(r => r.textContent?.includes('bash-2'));
		expect(doneRow?.textContent).toContain('02:00');
		// 终态行弱化（opacity-60）。
		expect(doneRow?.className).toContain('opacity-60');
	});

	it('空集 = 删除键：GET 返回空后控件消失且 store 无键', async () => {
		seed('s1', [job({job_id: 'bash-1', status: 'running'})]);
		fetchSessionJobsMock.mockResolvedValue({jobs: [], version: 0});
		const {container} = render(<SessionJobsBadge sessionId="s1" />);
		expect(container).not.toBeEmptyDOMElement();
		await waitFor(() => {
			expect(
				useChatStore.getState().sessionJobsById['s1'],
			).toBeUndefined();
		});
		await waitFor(() => {
			expect(container).toBeEmptyDOMElement();
		});
	});
});
