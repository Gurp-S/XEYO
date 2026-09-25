/**
 * AgentDoneBars.test.tsx — 子任务取消/重试的失败必须有痕迹。
 *
 * 旧实现是 `void cancelAgentTask(...)`：存储层返回的 boolean 被丢掉，
 * 取消没被接受时界面既不写状态也不提示，用户只能觉得"按钮卡了一下"，
 * 然后继续等一个不会停的子 Agent。
 */
import {cleanup, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import type {MultiAgentTaskView} from '@/lib/api';

const toast = {error: vi.fn(), info: vi.fn(), success: vi.fn(), warn: vi.fn(), dismiss: vi.fn()};
vi.mock('@/lib/toast', () => ({toast}));

const {useChatStore} = await import('@/stores/chatStore');
const {AgentDoneBars} = await import('@/components/AgentDoneBars');

const cancelAgentTask = vi.fn();

const task: MultiAgentTaskView = {
	uid: 'u1',
	taskId: 't1',
	agentId: 'ag1',
	desc: '整理诊断清单',
	status: 'running',
} as MultiAgentTaskView;

beforeEach(() => {
	toast.error.mockReset();
	cancelAgentTask.mockReset();
	useChatStore.setState({
		activeId: 's1',
		sessions: [],
		cancelAgentTask,
	} as never);
});

afterEach(() => {
	cleanup();
	useChatStore.setState({activeId: null, cancelAgentTask: undefined} as never);
});

describe('AgentDoneBars 的取消', () => {
	it('取消被接受时不报警', async () => {
		cancelAgentTask.mockResolvedValue(true);
		render(<AgentDoneBars tasks={[task]} />);
		await userEvent.click(screen.getByRole('button', {name: /取消/}));

		expect(cancelAgentTask).toHaveBeenCalledWith('s1', 'ag1');
		expect(toast.error).not.toHaveBeenCalled();
	});

	it('取消未被接受时必须说出来（过去是静默丢弃）', async () => {
		cancelAgentTask.mockResolvedValue(false);
		render(<AgentDoneBars tasks={[task]} />);
		await userEvent.click(screen.getByRole('button', {name: /取消/}));

		expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('未被接受'));
	});
});
