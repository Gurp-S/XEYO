/**
 * MemorySwitchesSetting.test.tsx — 开关面板在"读不出"时不许宣称"没有开关"。
 *
 * 这一屏是开关权威的唯一界面：把 403/离线画成"当前无产品可切换的记忆开关"，
 * 用户读到的是一句关于开关状态的事实，而实际是我们没读到。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';

const getMock = vi.fn();
const setMock = vi.fn();
const toastError = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		getMemorySwitches: () => getMock(),
		setMemorySwitches: (...args: unknown[]) => setMock(...args),
	};
});

vi.mock('@/lib/toast', () => ({
	toast: {
		error: (...args: unknown[]) => toastError(...args),
		success: vi.fn(),
	},
}));

/* eslint-disable import/first */
import {MemorySwitchesSetting} from './MemorySwitchesSetting';

const sw = (over: Record<string, unknown> = {}) => ({
	key: 'XEYO_WSC',
	label: '上下文压缩',
	value: '1',
	allowed: ['0', '1'],
	source: 'settings',
	default: '0',
	exposed: true,
	effective: '1',
	...over,
});

beforeEach(() => {
	getMock.mockReset();
	setMock.mockReset();
	toastError.mockReset();
});

afterEach(() => {
	cleanup();
});

describe('读不出时', () => {
	it('说明原因、给重试，且不出现"无产品可切换的开关"', async () => {
		getMock.mockResolvedValue({ok: false, data: null, message: 'loopback only'});

		render(<MemorySwitchesSetting />);

		await waitFor(() => expect(screen.getByText(/loopback only/)).toBeTruthy());
		expect(screen.getByText(/未读到记忆开关状态/)).toBeTruthy();
		expect(screen.queryByText(/当前无产品可切换的记忆开关/)).toBeNull();
	});

	it('重试会重新读一次并恢复渲染', async () => {
		getMock.mockResolvedValueOnce({ok: false, data: null, message: 'HTTP 503'});
		render(<MemorySwitchesSetting />);
		await screen.findByText(/HTTP 503/);

		getMock.mockResolvedValueOnce({ok: true, data: {ok: true, switches: {a: sw()}}, message: ''});
		fireEvent.click(screen.getByRole('button', {name: '重试'}));

		await waitFor(() => expect(screen.getByText('上下文压缩')).toBeTruthy());
		expect(getMock).toHaveBeenCalledTimes(2);
	});
});

describe('读到之后', () => {
	it('只渲染 exposed 项，并按 effective 显示当前值与来源', async () => {
		getMock.mockResolvedValue({
			ok: true,
			data: {
				ok: true,
				switches: {
					a: sw(),
					b: sw({key: 'XEYO_HIDDEN', label: '测试开关', exposed: false}),
				},
			},
			message: '',
		});

		render(<MemorySwitchesSetting />);

		await screen.findByText('上下文压缩');
		expect(screen.queryByText('测试开关')).toBeNull();
		expect(screen.getByText(/当前: 1（settings）/)).toBeTruthy();
	});

	it('某行缺 allowed：不崩、该行禁用并说明原因', async () => {
		getMock.mockResolvedValue({
			ok: true,
			data: {ok: true, switches: {a: sw({allowed: undefined})}},
			message: '',
		});

		render(<MemorySwitchesSetting />);

		const row = await screen.findByRole('button', {name: /上下文压缩/});
		expect(row).toBeDisabled();
		expect(row.textContent).toContain('回执未给可取值');
	});

	it('切换被后端按 200 拒绝时，toast 带原话', async () => {
		getMock.mockResolvedValue({
			ok: true,
			data: {ok: true, switches: {a: sw()}},
			message: '',
		});
		setMock.mockResolvedValue({
			ok: false,
			data: null,
			message: '未知记忆开关: XEYO_WSC',
		});

		render(<MemorySwitchesSetting />);
		const row = await screen.findByRole('button', {name: /上下文压缩/});

		fireEvent.click(row);

		await waitFor(() => expect(setMock).toHaveBeenCalled());
		expect(toastError).toHaveBeenCalled();
		expect(String(toastError.mock.calls[0][0])).toContain('未知记忆开关: XEYO_WSC');
	});
});
