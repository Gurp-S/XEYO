/**
 * BashRoutingSetting.test.tsx — 工作区 Bash 策略面板的读数。
 *
 * 这个面板以前在"没读到"的时候照样把 推荐 3 / 上限 5 印在界面上
 * （客户端默认值），并把控件留在可点状态；读不出与读到必须分家。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';

const loadMock = vi.fn();
const saveMock = vi.fn();
const toastError = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		loadBashPolicy: (...args: unknown[]) => loadMock(...args),
		saveBashPolicy: (...args: unknown[]) => saveMock(...args),
	};
});

vi.mock('@/lib/toast', () => ({
	toast: {error: (...args: unknown[]) => toastError(...args), info: vi.fn()},
}));

vi.mock('@/stores/chatStore', () => {
	const state = {
		activeSpaceId: 'sp1',
		spaces: [{id: 'sp1', rootPath: 'D:/proj'}],
	};
	const useChatStore = (selector?: (s: typeof state) => unknown) =>
		selector ? selector(state) : state;
	useChatStore.getState = () => state;
	return {useChatStore};
});

/* eslint-disable import/first */
import {BashRoutingSetting} from './BashRoutingSetting';

const policy = (over: Record<string, unknown> = {}) => ({
	ok: true,
	cwd: 'D:/proj',
	bash_routing: 'auto' as const,
	bash_escalate: 4,
	escalate_recommended: 4,
	escalate_max: 9,
	escalate_min: 0,
	...over,
});

beforeEach(() => {
	loadMock.mockReset();
	saveMock.mockReset();
	toastError.mockReset();
});

afterEach(() => {
	cleanup();
});

describe('读到策略时', () => {
	it('推荐值与上限用后端给的数，不是客户端默认', async () => {
		loadMock.mockResolvedValue({ok: true, policy: policy(), message: ''});

		render(<BashRoutingSetting />);

		await waitFor(() => expect(screen.getByText(/推荐 4/)).toBeTruthy());
		expect(screen.getByText(/上限 9/)).toBeTruthy();
		expect(screen.getByDisplayValue('4')).toBeTruthy();
		expect(screen.getByRole('button', {name: '保存'})).not.toBeDisabled();
	});

	it('保存成功后按后端回执回填（后端夹过的值以回执为准）', async () => {
		loadMock.mockResolvedValue({ok: true, policy: policy(), message: ''});
		saveMock.mockResolvedValue({
			ok: true,
			policy: policy({bash_escalate: 9}),
			message: '',
		});

		render(<BashRoutingSetting />);
		await waitFor(() => expect(screen.getByText(/上限 9/)).toBeTruthy());

		fireEvent.click(screen.getByRole('button', {name: '保存'}));

		await waitFor(() => expect(saveMock).toHaveBeenCalled());
		expect(screen.getByDisplayValue('9')).toBeTruthy();
		expect(screen.getByRole('button', {name: '已保存'})).toBeTruthy();
	});
});

describe('读不出时', () => {
	it('说明原因，并锁住两个控件与保存（不让按没读到的策略改配置）', async () => {
		loadMock.mockResolvedValue({
			ok: false,
			policy: null,
			message: 'loopback only',
		});

		render(<BashRoutingSetting />);

		await waitFor(() => expect(screen.getByText(/loopback only/)).toBeTruthy());
		expect(screen.getByText(/未读到工作区策略/)).toBeTruthy();
		// 不印客户端默认值。
		expect(screen.getByText(/推荐 未取回/)).toBeTruthy();
		expect(screen.getByText(/上限 未取回/)).toBeTruthy();
		expect(screen.getByRole('combobox')).toBeDisabled();
		expect(screen.getByRole('button', {name: '保存'})).toBeDisabled();
	});

	it('形状不对（缺 escalate_max）也算读不出', async () => {
		loadMock.mockResolvedValue({
			ok: false,
			policy: null,
			message: 'receipt_bad_policy',
		});

		render(<BashRoutingSetting />);

		await waitFor(() =>
			expect(screen.getByText(/receipt_bad_policy/)).toBeTruthy(),
		);
		expect(screen.queryByText(/上限 5/)).toBeNull();
	});

	it('保存失败：带原因的 toast，且不出现"已保存"', async () => {
		loadMock.mockResolvedValue({ok: true, policy: policy(), message: ''});
		saveMock.mockResolvedValue({
			ok: false,
			policy: null,
			message: 'bash_escalate must be <= 9',
		});

		render(<BashRoutingSetting />);
		await waitFor(() => expect(screen.getByText(/上限 9/)).toBeTruthy());

		fireEvent.click(screen.getByRole('button', {name: '保存'}));

		await waitFor(() => expect(toastError).toHaveBeenCalled());
		expect(String(toastError.mock.calls[0][0])).toContain('must be <= 9');
		expect(screen.getByRole('button', {name: '保存'})).toBeTruthy();
	});
});
