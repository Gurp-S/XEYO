/**
 * A3SnapshotPanel.test.tsx — 用量页主面的三种读数必须分家。
 *
 * "报告存在" / "后端确认还没生成" / "我们没读到" 是三件事。
 * 客户端原来把后两种压成 null，面板于是对着一次 403 说"还没有 A3 快照"。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';

const reportMock = vi.fn();
const snapshotMock = vi.fn();
const toastError = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		getMemoryReport: () => reportMock(),
		runMemorySnapshot: () => snapshotMock(),
		memoryReportViewUrl: () => 'http://127.0.0.1:8000/v1/settings/memory/report/view',
	};
});

vi.mock('@/lib/openExternal', () => ({openExternalUrl: vi.fn(async () => {})}));
vi.mock('@/lib/toast', () => ({
	toast: {error: (...args: unknown[]) => toastError(...args), success: vi.fn()},
}));

/* eslint-disable import/first */
import {A3SnapshotPanel} from './A3SnapshotPanel';

const EXISTS = {
	ok: true,
	exists: true,
	path: 'D:/docs/A3-monitor.html',
	url: 'file:///D:/docs/A3-monitor.html',
	bytes: 4096,
	mtime: 1,
	generated_at: '2026-09-24T09:30:00',
	days: ['2026-09-23', '2026-09-24'],
};

beforeEach(() => {
	reportMock.mockReset();
	snapshotMock.mockReset();
	toastError.mockReset();
});

afterEach(() => {
	cleanup();
});

describe('报告状态', () => {
	it('读不出：写明原因，且不出现"还没有 A3 快照"', async () => {
		reportMock.mockResolvedValue({ok: false, data: null, message: 'loopback only'});

		render(<A3SnapshotPanel active />);

		await waitFor(() =>
			expect(screen.getByText(/未读到 A3 报告状态（loopback only）/)).toBeTruthy(),
		);
		expect(screen.queryByText(/还没有 A3 快照/)).toBeNull();
		expect(screen.getByRole('button', {name: '新窗口'})).toBeDisabled();
	});

	it('后端确认还没生成：才允许说"尚未生成报告"', async () => {
		reportMock.mockResolvedValue({
			ok: true,
			data: {ok: false, exists: false, path: 'D:/docs/A3-monitor.html', url: ''},
			message: '',
		});

		render(<A3SnapshotPanel active />);

		await waitFor(() => expect(screen.getByText('尚未生成报告')).toBeTruthy());
		expect(screen.getByText(/还没有 A3 快照/)).toBeTruthy();
	});

	it('报告存在：头部给文件名 / 天数 / 大小，并挂上预览', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});

		render(<A3SnapshotPanel active />);

		await waitFor(() => expect(screen.getByText(/A3-monitor\.html/)).toBeTruthy());
		expect(screen.getByText(/2 天/)).toBeTruthy();
		expect(screen.getByText(/4 KB/)).toBeTruthy();
		expect(screen.getByTitle('A3 日常监控报告')).toBeTruthy();
		expect(screen.getByRole('button', {name: '新窗口'})).not.toBeDisabled();
	});

	it('刷新按钮会重读一次', async () => {
		reportMock
			.mockResolvedValueOnce({ok: false, data: null, message: 'HTTP 503'})
			.mockResolvedValueOnce({ok: true, data: EXISTS, message: ''});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/HTTP 503/);

		fireEvent.click(screen.getByRole('button', {name: '刷新 A3 报告状态'}));

		await waitFor(() => expect(reportMock).toHaveBeenCalledTimes(2));
		await waitFor(() => expect(screen.getByText(/A3-monitor\.html/)).toBeTruthy());
		expect(screen.queryByText(/未读到 A3 报告状态/)).toBeNull();
	});
});

describe('立即快照', () => {
	it('读不到回执时说"未确认"，不说"失败"', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		snapshotMock.mockResolvedValue({ok: false, data: null, message: 'Failed to fetch'});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/A3-monitor\.html/);

		fireEvent.click(screen.getByRole('button', {name: '立即快照'}));

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		const msg = String(toastError.mock.calls[0][0]);
		expect(msg).toContain('未确认');
		expect(msg).not.toContain('A3 快照失败');
	});

	it('后端自报失败时用它的原话', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		snapshotMock.mockResolvedValue({
			ok: true,
			data: {ok: false, error: '生成器退出码 1'},
			message: '',
		});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/A3-monitor\.html/);

		fireEvent.click(screen.getByRole('button', {name: '立即快照'}));

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(String(toastError.mock.calls[0][0])).toContain('生成器退出码 1');
	});

	it('补齐多天成功后写清补齐范围，并刷新报告', async () => {
		reportMock.mockResolvedValue({ok: true, data: EXISTS, message: ''});
		snapshotMock.mockResolvedValue({
			ok: true,
			data: {ok: true, days: ['2026-09-20', '2026-09-21', '2026-09-22']},
			message: '',
		});

		render(<A3SnapshotPanel active />);
		await screen.findByText(/A3-monitor\.html/);

		fireEvent.click(screen.getByRole('button', {name: '立即快照'}));

		await waitFor(() =>
			expect(screen.getByText(/补齐 3 天（2026-09-20 → 2026-09-22）/)).toBeTruthy(),
		);
		expect(reportMock).toHaveBeenCalledTimes(2);
	});
});
