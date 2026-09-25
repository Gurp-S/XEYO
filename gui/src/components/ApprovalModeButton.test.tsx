/**
 * 审批模式按钮：写失败的读数。
 *
 * 要害是"收紧没生效"与"放开没生效"都可能被读成已生效。这里不滚回用户点的档位
 * （没有活值的会话里，请求 body 才是生效通道，滚回去等于替他改回旧档），
 * 而是照他点的显示 + 标出"本会话未确认生效"。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';

const mocks = vi.hoisted(() => {
	const state = {mode: 'risk', activeId: 'sess_A' as string | null};
	return {
		state,
		write: vi.fn(),
		patchDraft: vi.fn(),
		toastError: vi.fn(),
		update: vi.fn((patch: {permissionMode?: string}) => {
			if (patch.permissionMode) state.mode = patch.permissionMode;
		}),
	};
});

vi.mock('@/lib/api/runtimeMode', () => ({
	setSessionRuntimeMode: (...args: unknown[]) => mocks.write(...args),
}));
vi.mock('@/lib/composerDrafts', () => ({
	patchComposerDraftModes: (...args: unknown[]) => mocks.patchDraft(...args),
}));
vi.mock('@/lib/toast', () => ({
	toast: {error: (...args: unknown[]) => mocks.toastError(...args), success: vi.fn()},
}));
vi.mock('@/stores/settingsStore', () => ({
	useSettingsStore: (sel: (s: {permissionMode: string; update: unknown}) => unknown) =>
		sel({permissionMode: mocks.state.mode, update: mocks.update}),
}));
vi.mock('@/stores/chatUiStore', () => ({
	useChatUiStore: (sel: (s: {activeId: string | null}) => unknown) =>
		sel({activeId: mocks.state.activeId}),
}));

import {ApprovalModeButton} from './ApprovalModeButton';

const TRIGGER = '审批模式';
const TRIGGER_UNCONFIRMED = '审批模式（本会话未确认生效）';

/** 菜单项的可访问名是"标签 + 说明"整串，而 risk 的说明里也写着"请求批准" ⇒ 必须锚住开头。 */
function pick(name: RegExp) {
	fireEvent.click(screen.getByRole('button', {name: TRIGGER}));
	fireEvent.click(screen.getByRole('menuitem', {name}));
}

beforeEach(() => {
	mocks.state.mode = 'risk';
	mocks.state.activeId = 'sess_A';
	mocks.write.mockReset();
	mocks.patchDraft.mockReset();
	mocks.toastError.mockReset();
	mocks.update.mockClear();
});

afterEach(() => {
	cleanup();
});

describe('写入回执决定读数', () => {
	it('写成功：只有档名，不带"未确认"标记', async () => {
		mocks.write.mockResolvedValue({ok: true, mode: 'never', message: ''});

		render(<ApprovalModeButton />);
		pick(/^完全访问权限/);

		await waitFor(() => expect(mocks.write).toHaveBeenCalledWith('sess_A', 'never'));
		expect(screen.getByRole('button', {name: TRIGGER})).toBeTruthy();
		expect(screen.queryByRole('button', {name: TRIGGER_UNCONFIRMED})).toBeNull();
		expect(mocks.toastError).not.toHaveBeenCalled();
	});

	it('写失败：保留用户点的档位，但标出未确认并带原因', async () => {
		mocks.write.mockResolvedValue({ok: false, mode: '', message: 'loopback only'});

		render(<ApprovalModeButton />);
		pick(/^请求批准/);

		const btn = await screen.findByRole('button', {name: TRIGGER_UNCONFIRMED});
		// 不滚回：显示的仍是用户要的那一档（当前标签取自 store）。
		expect(btn.textContent).toContain('请求批准');
		expect(btn.getAttribute('title')).toContain('loopback only');
		expect(mocks.update).toHaveBeenCalledWith({permissionMode: 'always'});
		await waitFor(() => expect(mocks.toastError).toHaveBeenCalled());
		expect(String(mocks.toastError.mock.calls[0][0])).toContain('loopback only');
	});

	it('旧会话的迟到失败回执不得盖到新会话头上', async () => {
		const releasers: Array<(v: {ok: boolean; mode: string; message: string}) => void> = [];
		mocks.write.mockImplementation(
			() =>
				new Promise(resolve => {
					releasers.push(resolve);
				}),
		);

		const {rerender} = render(<ApprovalModeButton />);
		pick(/^完全访问权限/);
		expect(releasers).toHaveLength(1);

		mocks.state.activeId = 'sess_B';
		rerender(<ApprovalModeButton />);
		releasers[0]!({ok: false, mode: '', message: 'loopback only'});
		await new Promise(r => setTimeout(r, 0));

		expect(screen.getByRole('button', {name: TRIGGER})).toBeTruthy();
		expect(screen.queryByRole('button', {name: TRIGGER_UNCONFIRMED})).toBeNull();
	});

	it('没有活动会话时不发写请求，也不标未确认', () => {
		mocks.state.activeId = null;

		render(<ApprovalModeButton />);
		pick(/^请求批准/);

		expect(mocks.write).not.toHaveBeenCalled();
		expect(mocks.patchDraft).not.toHaveBeenCalled();
		expect(screen.getByRole('button', {name: TRIGGER})).toBeTruthy();
	});

	it('菜单选择会把本会话的草稿一起改掉', async () => {
		mocks.write.mockResolvedValue({ok: true, mode: 'always', message: ''});

		render(<ApprovalModeButton />);
		pick(/^请求批准/);
		// 回执落地会改 state：不等它flush 完就断言，React 会报"没包在 act 里"。
		await act(async () => {
			await Promise.resolve();
		});

		expect(mocks.patchDraft).toHaveBeenCalledWith('sess_A', {permissionMode: 'always'});
	});
});
