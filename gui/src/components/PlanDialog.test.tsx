/**
 * PlanDialog.test.tsx — 计划裁决的发送顺序与回执读取。
 *
 * 旧实现是：先把面板清掉，再 `void resolvePlan(...)` 且不看结果。
 * 于是请求没送达时，引擎仍在等这个计划，而界面上已经没有能答它的入口了 ——
 * 这是三个裁决面板里唯一一个"先清后发"的（审批/提问面板都反过来，注释还写着原因）。
 */
import {act, cleanup, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

const resolvePlan = vi.fn();
const toast = {error: vi.fn(), info: vi.fn(), success: vi.fn(), warn: vi.fn(), dismiss: vi.fn()};

vi.mock('@/lib/api', async importOriginal => {
	const real = await importOriginal<typeof import('@/lib/api')>();
	return {...real, resolvePlan: (...args: unknown[]) => resolvePlan(...args)};
});

vi.mock('@/lib/toast', () => ({toast}));

const {useChatStore} = await import('@/stores/chatStore');
const {PlanDialog} = await import('@/components/PlanDialog');

function seed() {
	useChatStore.setState({
		activeId: 's1',
		pendingPlan: {requestId: 'p1', plan: '分三步实施', sessionId: 's1'},
	} as never);
}

beforeEach(() => {
	resolvePlan.mockReset();
	toast.error.mockReset();
	toast.info.mockReset();
	seed();
});

afterEach(() => {
	cleanup();
	useChatStore.setState({activeId: null, pendingPlan: null} as never);
});

describe('PlanDialog', () => {
	it('裁决送达并生效后才收起面板', async () => {
		resolvePlan.mockResolvedValue({ok: true, reason: '', message: ''});
		render(<PlanDialog />);
		await userEvent.click(screen.getByText('允许执行'));

		expect(resolvePlan).toHaveBeenCalledWith('p1', true);
		expect(useChatStore.getState().pendingPlan).toBeNull();
		expect(toast.error).not.toHaveBeenCalled();
	});

	it('请求没送达时面板必须留着：引擎还在等这个计划', async () => {
		resolvePlan.mockResolvedValue({ok: false, reason: 'network', message: 'Failed to fetch'});
		render(<PlanDialog />);
		await userEvent.click(screen.getByText('拒绝'));

		expect(useChatStore.getState().pendingPlan).not.toBeNull();
		expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('提交未生效'));
	});

	it('"已在别处答复"要收起面板并按信息提示，不是失败', async () => {
		resolvePlan.mockResolvedValue({ok: false, reason: 'already_resolved', message: 'x'});
		render(<PlanDialog />);
		await userEvent.click(screen.getByText('允许执行'));

		expect(useChatStore.getState().pendingPlan).toBeNull();
		expect(toast.info).toHaveBeenCalledWith(expect.stringContaining('已在别处答复'));
		expect(toast.error).not.toHaveBeenCalled();
	});

	it('连点两次只发一次裁决', async () => {
		let release: (v: {ok: boolean; reason: string; message: string}) => void = () => {};
		resolvePlan.mockImplementation(
			() => new Promise(res => {
				release = res;
			}),
		);
		render(<PlanDialog />);
		await userEvent.click(screen.getByText('允许执行'));
		await userEvent.click(screen.getByText('允许执行'));
		expect(resolvePlan).toHaveBeenCalledTimes(1);
		await act(async () => {
			release({ok: true, reason: '', message: ''});
		});
	});
});
