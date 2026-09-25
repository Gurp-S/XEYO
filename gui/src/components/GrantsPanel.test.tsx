/**
 * 授权面板：读不出时绝不画成"暂无授权"；撤销没生效时绝不念成"撤销失败请重试"。
 *
 * 两条是同一件事——安全台账上"我没读到"与"确实没有"差很远；
 * "这条已不在台账"与"撤销动作失败"也差很远（前者重试永远修不好）。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {GrantsPanel} from '@/components/GrantsPanel';

const listMock = vi.fn();
const revokeMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();
const toastInfo = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		listPermissionGrants: () => listMock(),
		revokePermissionGrant: (id: string) => revokeMock(id),
	};
});

vi.mock('@/lib/inlineDialog', () => ({
	confirmDialog: vi.fn(() => Promise.resolve(true)),
}));
vi.mock('@/lib/toast', () => ({
	toast: {
		success: (...args: unknown[]) => toastSuccess(...args),
		error: (...args: unknown[]) => toastError(...args),
		info: (...args: unknown[]) => toastInfo(...args),
	},
}));

const grant = {
	grant_id: 'a1b2c3d4e5f6',
	tool_name: 'Bash',
	fingerprint: 'fp:deadbeef',
	scope: 'D:/proj',
	created_at: 1,
	expires_at: null,
	actor: 'desktop',
};

beforeEach(() => {
	listMock.mockReset();
	revokeMock.mockReset();
	toastSuccess.mockClear();
	toastError.mockClear();
	toastInfo.mockClear();
});

afterEach(() => {
	cleanup();
});

describe('GrantsPanel 读取失败', () => {
	it('展示原因而不是"暂无授权"', async () => {
		listMock.mockResolvedValue({
			ok: false,
			grants: [],
			message: 'invalid or missing token',
		});

		render(<GrantsPanel />);

		await waitFor(() => expect(screen.getByText(/读取授权列表失败/)).toBeTruthy());
		expect(screen.queryByText(/暂无授权/)).toBeNull();
		expect(screen.getByText(/现在显示的不代表真实授权/)).toBeTruthy();
	});

	it('已有旧列表时保留条目并提示可能不是最新', async () => {
		listMock
			.mockResolvedValueOnce({ok: true, grants: [grant], message: ''})
			.mockResolvedValueOnce({ok: false, grants: [], message: 'HTTP 503'});

		render(<GrantsPanel />);
		await waitFor(() => expect(screen.getByText(/fp:deadbeef/)).toBeTruthy());

		fireEvent.click(screen.getByRole('button', {name: '刷新'}));

		await waitFor(() => expect(screen.getByText(/可能不是最新/)).toBeTruthy());
		expect(screen.getByText(/fp:deadbeef/)).toBeTruthy();
	});

	it('真的空台账才显示"暂无授权"', async () => {
		listMock.mockResolvedValue({ok: true, grants: [], message: ''});

		render(<GrantsPanel />);

		await waitFor(() => expect(screen.getByText(/暂无授权/)).toBeTruthy());
		expect(screen.queryByText(/读取授权列表失败/)).toBeNull();
	});
});

/** 撤销动作的回执：三种"没改成"在界面上必须是三句话。 */
describe('GrantsPanel 撤销的回执', () => {
	async function clickRevoke() {
		render(<GrantsPanel />);
		await waitFor(() => expect(screen.getByText(/fp:deadbeef/)).toBeTruthy());
		fireEvent.click(screen.getByRole('button', {name: '撤销此授权'}));
	}

	it('ok:true → 提示已撤销，并重读列表把行拿掉', async () => {
		listMock
			.mockResolvedValueOnce({ok: true, grants: [grant], message: ''})
			.mockResolvedValueOnce({ok: true, grants: [], message: ''});
		revokeMock.mockResolvedValue({ok: true, reason: '', message: ''});

		await clickRevoke();

		await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('已撤销授权'));
		expect(toastError).not.toHaveBeenCalled();
		await waitFor(() => expect(screen.getByText(/暂无授权/)).toBeTruthy());
		expect(revokeMock).toHaveBeenCalledWith('a1b2c3d4e5f6');
	});

	it('后端说这条已不在台账 → 说"已不在台账"而不是"失败请重试"，并重读', async () => {
		listMock
			.mockResolvedValueOnce({ok: true, grants: [grant], message: ''})
			.mockResolvedValueOnce({ok: true, grants: [], message: ''});
		revokeMock.mockResolvedValue({
			ok: false,
			reason: 'grant_not_found',
			message: 'grant_not_found',
		});

		await clickRevoke();

		await waitFor(() => expect(toastInfo).toHaveBeenCalled());
		expect(String(toastInfo.mock.calls[0][0])).toContain('已不在台账');
		expect(String(toastInfo.mock.calls[0][0])).not.toContain('重试');
		expect(toastError).not.toHaveBeenCalled();
		await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
	});

	it('403 被门禁挡下 → 带后端原话，且不能把它读成"已撤销"', async () => {
		listMock.mockResolvedValue({ok: true, grants: [grant], message: ''});
		revokeMock.mockResolvedValue({ok: false, reason: 'http', message: 'local only'});

		await clickRevoke();

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(String(toastError.mock.calls[0][0])).toContain('撤销未生效：local only');
		expect(toastSuccess).not.toHaveBeenCalled();
		expect(screen.getByText(/fp:deadbeef/)).toBeTruthy();
	});

	it('取消确认框时不发请求', async () => {
		const {confirmDialog} = await import('@/lib/inlineDialog');
		vi.mocked(confirmDialog).mockResolvedValueOnce(false);
		listMock.mockResolvedValue({ok: true, grants: [grant], message: ''});

		await clickRevoke();

		await waitFor(() => expect(confirmDialog).toHaveBeenCalled());
		expect(revokeMock).not.toHaveBeenCalled();
	});
});
