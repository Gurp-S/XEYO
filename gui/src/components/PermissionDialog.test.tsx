import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {PermissionDialog} from './PermissionDialog';

const {resolvePermission, toastInfo, setPendingPermission} = vi.hoisted(() => ({
	resolvePermission: vi.fn(async (..._args: unknown[]) => ({ok: true})),
	toastInfo: vi.fn(),
	setPendingPermission: vi.fn(),
}));

let fixture: Record<string, unknown> | null = null;

vi.mock('@/hooks/usePendingForActiveSession', () => ({
	usePendingPermissionForActiveSession: () => fixture,
}));
vi.mock('@/lib/api', () => ({
	resolvePermission,
	resolveFailureText: () => ({tone: 'error', text: 'x'}),
}));
vi.mock('@/lib/toast', () => ({
	toast: {info: toastInfo, error: vi.fn(), warn: vi.fn()},
}));
vi.mock('@/lib/heartbeat', () => ({useHeartbeat: () => {}}));
vi.mock('@/stores/chatStore', () => ({
	useChatStore: {getState: () => ({pendingPermission: fixture, setPendingPermission})},
}));
vi.mock('@/stores/settingsStore', () => ({
	isSmoothnessOn: () => false,
	useSettingsStore: (sel: (s: {smoothness: string}) => unknown) =>
		sel({smoothness: 'off'}),
}));

// jsdom 没有 ResizeObserver，而面板用它量命令区是否超长（同 A3NativePanel 的先例）。
class ResizeObserverStub {
	observe(): void {}
	unobserve(): void {}
	disconnect(): void {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub);

function ask(partial: Record<string, unknown>) {
	fixture = {
		requestId: 'r1',
		toolName: 'Read',
		prompt: 'Allow Read to read D:\\notes\\a.txt? It is outside the workspace.',
		reason: 'needs_confirmation',
		sessionId: 's1',
		intent: 'confirm',
		expiresAt: null,
		...partial,
	};
}

beforeEach(() => {
	resolvePermission.mockClear();
	toastInfo.mockClear();
	setPendingPermission.mockClear();
	fixture = null;
});

describe('PermissionDialog 「不再询问」适用范围', () => {
	it('区外读的确认给出目录粒度的勾选', () => {
		ask({reason: 'read_outside_working_directory'});
		render(<PermissionDialog />);
		expect(screen.queryByText('不再询问该目录及其子目录')).not.toBeNull();
		expect(screen.queryByText('不再询问此类命令')).toBeNull();
	});

	it('Bash 确认仍给出命令前缀粒度的勾选', () => {
		ask({toolName: 'Bash', reason: 'needs_confirmation'});
		render(<PermissionDialog />);
		expect(screen.queryByText('不再询问此类命令')).not.toBeNull();
		expect(screen.queryByText('不再询问该目录及其子目录')).toBeNull();
	});

	it('其它确认（如工作区内写）不提供勾选：勾了也记不住的东西不能出现在面板上', () => {
		ask({toolName: 'Write', reason: 'needs_confirmation'});
		render(<PermissionDialog />);
		expect(screen.queryByRole('checkbox')).toBeNull();
	});

	it('勾选后放行把 remember 发出去，且回执文案说的是目录', async () => {
		ask({reason: 'read_outside_working_directory'});
		render(<PermissionDialog />);
		fireEvent.click(screen.getByRole('checkbox'));
		fireEvent.click(screen.getByText('允许'));
		await waitFor(() => expect(resolvePermission).toHaveBeenCalled());
		const args = resolvePermission.mock.calls[0];
		expect(args[0]).toBe('r1');
		expect(args[1]).toBe(true);
		expect(args[4]).toBe(true);
		await waitFor(() => expect(toastInfo).toHaveBeenCalled());
		expect(String(toastInfo.mock.calls[0][0])).toContain('该目录及其子目录');
	});

	it('不勾选时 remember 必须是 false（不能默认放宽）', async () => {
		ask({reason: 'read_outside_working_directory'});
		render(<PermissionDialog />);
		fireEvent.click(screen.getByText('允许'));
		await waitFor(() => expect(resolvePermission).toHaveBeenCalled());
		expect(resolvePermission.mock.calls[0][4]).toBe(false);
	});
});
