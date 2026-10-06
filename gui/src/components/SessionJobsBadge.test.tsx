/**
 * SessionJobsBadge（F3 统一总览）：job + 运行中子代理合一列表，子代理可打开/停止。
 */
import {cleanup, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

const toast = {error: vi.fn(), info: vi.fn(), success: vi.fn(), warn: vi.fn(), dismiss: vi.fn()};
vi.mock('@/lib/toast', () => ({toast}));

const {useChatStore} = await import('@/stores/chatStore');
const {SessionJobsBadge} = await import('@/components/SessionJobsBadge');

const cancelAgentTask = vi.fn();
const openAgentView = vi.fn();

beforeEach(() => {
	toast.error.mockReset();
	cancelAgentTask.mockReset();
	openAgentView.mockReset();
	useChatStore.setState({
		activeId: 's1',
		sessions: [{id: 's1', archived: false}],
		sessionJobsById: {s1: []},
		multiAgentTasksBySession: {
			s1: [
				{
					uid: 'u1',
					taskId: 't1',
					agentId: 'ag1',
					desc: '整理诊断清单',
					status: 'running',
				},
			],
		},
		cancelAgentTask,
		openAgentView,
	} as never);
});

afterEach(() => {
	cleanup();
});

describe('SessionJobsBadge 统一总览（F3）', () => {
	it('只有运行中子代理时角标也在；弹层列出子代理', async () => {
		render(<SessionJobsBadge sessionId="s1" />);
		const badge = screen.getByRole('button', {name: /后台任务与子代理/});
		expect(badge.textContent).toContain('后台 1/1');
		await userEvent.click(badge);
		expect(screen.getByText(/子代理（1）/)).toBeTruthy();
		expect(screen.getByText(/整理诊断清单/)).toBeTruthy();
	});

	it('从总览停止子代理：调 store 动作；被拒时出声', async () => {
		cancelAgentTask.mockResolvedValueOnce(false);
		render(<SessionJobsBadge sessionId="s1" />);
		await userEvent.click(screen.getByRole('button', {name: /后台任务与子代理/}));
		await userEvent.click(screen.getByRole('button', {name: /停止子代理/}));
		expect(cancelAgentTask).toHaveBeenCalledWith('s1', 'ag1');
		expect(toast.error).toHaveBeenCalledWith(
			expect.stringContaining('未被接受'),
		);
	});

	it('点行前台化：开侧链并收起弹层', async () => {
		render(<SessionJobsBadge sessionId="s1" />);
		await userEvent.click(screen.getByRole('button', {name: /后台任务与子代理/}));
		await userEvent.click(screen.getByTitle('打开侧链（前台化）'));
		expect(openAgentView).toHaveBeenCalledWith('ag1');
		expect(screen.queryByText(/子代理（1）/)).toBeNull();
	});
});
