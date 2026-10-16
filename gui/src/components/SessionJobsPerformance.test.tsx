import {act, cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {useChatStore} from '@/stores/chatStore';
import {fetchJobOutput} from '@/lib/api/jobs';
import {SessionJobsBadge} from './SessionJobsBadge';

vi.mock('@/lib/api/jobs', async original => ({
	...await original<typeof import('@/lib/api/jobs')>(),
	fetchJobOutput: vi.fn(),
	fetchSessionJobs: vi.fn(async () => ({ok: false, jobs: []})),
}));
let visibility: DocumentVisibilityState;
beforeEach(() => {
	vi.useFakeTimers();
	visibility = 'visible';
	vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility);
	vi.mocked(fetchJobOutput).mockReset();
	useChatStore.setState({activeId: 's', historyById: {}, multiAgentTasksBySession: {}, sessionJobsById: {s: [{
		job_id: 'job', kind: 'terminal', label: '构建任务', status: 'running', detail: '', reported: false, started_at: 1, finished_at: 0,
	}]}});
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
function openOutput() {
	const view = render(<SessionJobsBadge sessionId="s" />);
	fireEvent.click(screen.getByRole('button', {name: /后台任务与子代理/}));
	fireEvent.click(screen.getByRole('button', {name: /构建任务/, expanded: false}));
	return view;
}
describe('后台任务输出轮询开销', () => {
	it('慢请求持续 10 秒时始终只有一个在途请求', async () => {
		vi.mocked(fetchJobOutput).mockImplementation(() => new Promise(() => {}));
		openOutput();
		await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
		console.info('PERF output requests during a 10s pending response:', vi.mocked(fetchJobOutput).mock.calls.length);
		expect(fetchJobOutput).toHaveBeenCalledTimes(1);
	});
	it('窗口隐藏时暂停，重新显示立即刷新，卸载后停止', async () => {
		vi.mocked(fetchJobOutput).mockResolvedValue(null);
		const view = openOutput();
		await act(async () => { await Promise.resolve(); });
		vi.mocked(fetchJobOutput).mockClear();
		act(() => { visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')); });
		await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
		console.info('PERF output requests during 10s hidden:', vi.mocked(fetchJobOutput).mock.calls.length);
		expect(fetchJobOutput).not.toHaveBeenCalled();
		await act(async () => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')); });
		expect(fetchJobOutput).toHaveBeenCalledTimes(1);
		view.unmount();
		await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
		expect(fetchJobOutput).toHaveBeenCalledTimes(1);
	});
});
