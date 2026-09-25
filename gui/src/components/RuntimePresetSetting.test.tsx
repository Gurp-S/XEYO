/**
 * RuntimePresetSetting.test.tsx — 权限 preset 面板必须把三种状态分画。
 *
 * 要害是安全语义：「已确认本会话没切换过」与「根本没读到它的当前档」不是一回事。
 * 旧实现里 403 / 后端没起 都塌成 `null`，面板于是画成"没有任何选中项"，
 * 再叠上脚注"未显式切换的会话仍沿用创建时钉死的 preset"——
 * 一句对用户自己的会话没做过的断言。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {useChatStore} from '@/stores/chatStore';
import {RuntimePresetSetting} from './RuntimePresetSetting';
import type {RuntimePresetRead, RuntimePresetWrite} from '@/lib/api/runtimePreset';

const readMock = vi.fn();
const writeMock = vi.fn();

vi.mock('@/lib/api/runtimePreset', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api/runtimePreset')>();
	return {
		...actual,
		fetchSessionRuntimePreset: (...args: unknown[]) => readMock(...args),
		setSessionRuntimePreset: (...args: unknown[]) => writeMock(...args),
	};
});

const toastError = vi.fn();
vi.mock('@/lib/toast', () => ({
	toast: {error: (...args: unknown[]) => toastError(...args), success: vi.fn()},
}));

const READ_OK = (preset: string | null): RuntimePresetRead => ({
	ok: true,
	preset,
	message: '',
});
const READ_FAIL = (message: string): RuntimePresetRead => ({
	ok: false,
	preset: null,
	message,
});
const WRITE_OK: RuntimePresetWrite = {ok: true, message: ''};

function pressed(label: RegExp): boolean {
	const btn = screen.getByRole('button', {name: label});
	return btn.getAttribute('aria-pressed') === 'true';
}

beforeEach(() => {
	readMock.mockReset();
	writeMock.mockReset();
	toastError.mockReset();
	useChatStore.setState({activeId: 'sess_A'});
});

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe('读得到时', () => {
	it('读到 null 说"已确认未显式切换"，且没有任何选中项', async () => {
		readMock.mockResolvedValue(READ_OK(null));

		render(<RuntimePresetSetting />);

		await waitFor(() =>
			expect(screen.getByText(/已确认本会话未显式切换过 preset/)).toBeTruthy(),
		);
		expect(screen.queryByText(/未能读取本会话当前的 preset/)).toBeNull();
		expect(pressed(/只读/)).toBe(false);
		expect(pressed(/工作区写/)).toBe(false);
		expect(pressed(/完全/)).toBe(false);
	});

	it('读到某一档时把它标成选中，且不出现状态提示行', async () => {
		readMock.mockResolvedValue(READ_OK('full'));

		render(<RuntimePresetSetting />);

		await waitFor(() => expect(pressed(/完全/)).toBe(true));
		expect(screen.queryByRole('status')).toBeNull();
	});

	it('读请求带的是当前会话 id', async () => {
		readMock.mockResolvedValue(READ_OK(null));

		render(<RuntimePresetSetting />);

		await waitFor(() => expect(readMock).toHaveBeenCalledWith('sess_A'));
	});
});

describe('读不出时', () => {
	it('展示后端原话，而不是"未显式切换"那行（旧实现在这里说谎）', async () => {
		readMock.mockResolvedValue(READ_FAIL('loopback only'));

		render(<RuntimePresetSetting />);

		await waitFor(() => expect(screen.getByText(/loopback only/)).toBeTruthy());
		expect(screen.getByText(/不代表它没有生效值/)).toBeTruthy();
		expect(screen.queryByText(/已确认本会话未显式切换过 preset/)).toBeNull();
	});

	it('没有活动会话时不发请求，并说明原因', async () => {
		useChatStore.setState({activeId: null});

		render(<RuntimePresetSetting />);

		await waitFor(() => expect(screen.getByText(/no_active_session/)).toBeTruthy());
		expect(readMock).not.toHaveBeenCalled();
	});

	it('读不出时写成功，"读不出"提示必须让位给写回执', async () => {
		readMock.mockResolvedValue(READ_FAIL('HTTP 503'));
		writeMock.mockResolvedValue(WRITE_OK);

		render(<RuntimePresetSetting />);
		await waitFor(() => expect(screen.getByText(/HTTP 503/)).toBeTruthy());

		fireEvent.click(screen.getByRole('button', {name: /只读/}));

		await waitFor(() => expect(pressed(/只读/)).toBe(true));
		expect(screen.queryByText(/未能读取本会话当前的 preset/)).toBeNull();
	});

	it('写失败时不回滚出"已确认"状态，仍留在读不出', async () => {
		readMock.mockResolvedValue(READ_FAIL('HTTP 503'));
		writeMock.mockResolvedValue({ok: false, message: 'loopback only'});

		render(<RuntimePresetSetting />);
		await waitFor(() => expect(screen.getByText(/HTTP 503/)).toBeTruthy());

		fireEvent.click(screen.getByRole('button', {name: /只读/}));

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(pressed(/只读/)).toBe(false);
		expect(screen.getByText(/HTTP 503/)).toBeTruthy();
	});
});

describe('切换与竞态', () => {
	it('旧会话的迟到回执不得覆盖新会话的读值', async () => {
		const resolvers: Array<(v: RuntimePresetRead) => void> = [];
		readMock.mockImplementation(
			() => new Promise<RuntimePresetRead>(resolve => resolvers.push(resolve)),
		);

		const {rerender} = render(<RuntimePresetSetting />);
		expect(readMock).toHaveBeenLastCalledWith('sess_A');

		await act(async () => {
			useChatStore.setState({activeId: 'sess_B'});
		});
		rerender(<RuntimePresetSetting />);
		expect(readMock).toHaveBeenLastCalledWith('sess_B');

		await act(async () => {
			resolvers[1](READ_OK('readonly'));
		});
		await waitFor(() => expect(pressed(/只读/)).toBe(true));

		// sess_A 的回执后到：它说 full，但当前会话是 sess_B 的 readonly。
		await act(async () => {
			resolvers[0](READ_OK('full'));
		});
		expect(pressed(/完全/)).toBe(false);
		expect(pressed(/只读/)).toBe(true);
	});

	it('写成功后显示"已生效"', async () => {
		readMock.mockResolvedValue(READ_OK(null));
		writeMock.mockResolvedValue(WRITE_OK);

		render(<RuntimePresetSetting />);
		await waitFor(() => expect(readMock).toHaveBeenCalled());

		fireEvent.click(screen.getByRole('button', {name: /工作区写/}));

		await waitFor(() => expect(screen.getByText('已生效')).toBeTruthy());
	});
});
