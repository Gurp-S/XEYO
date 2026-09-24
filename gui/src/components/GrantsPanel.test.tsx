/**
 * 授权面板：读不出时绝不画成"暂无授权"。
 *
 * 这条区分的是安全语义——"你没有放行任何命令"与"我没读到台账"差很远。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {GrantsPanel} from '@/components/GrantsPanel';

const listMock = vi.fn();

vi.mock('@/lib/api', () => ({
	listPermissionGrants: () => listMock(),
	revokePermissionGrant: vi.fn(),
}));

vi.mock('@/lib/inlineDialog', () => ({confirmDialog: vi.fn()}));
vi.mock('@/lib/toast', () => ({toast: {success: vi.fn(), error: vi.fn()}}));

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
