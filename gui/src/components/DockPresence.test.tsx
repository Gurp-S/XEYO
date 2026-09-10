import {act, cleanup, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {PRESENCE_EXIT_MARGIN_MS, cssDurationMs, presenceExitMs} from '@/lib/motionDuration';
import {DockPresence} from './DockPresence';

describe('DockPresence', () => {
	afterEach(() => {
		cleanup();
		vi.useRealTimers();
	});

	it('unmounts immediately when smoothness is off', () => {
		const {rerender} = render(
			<DockPresence open smoothness={false}>
				<span>todo</span>
			</DockPresence>,
		);
		expect(screen.getByText('todo')).toBeInTheDocument();
		rerender(
			<DockPresence open={false} smoothness={false}>
				<span>todo</span>
			</DockPresence>,
		);
		expect(screen.queryByText('todo')).not.toBeInTheDocument();
	});

	it('keeps children during exit when smoothness is on', () => {
		vi.useFakeTimers();
		const {rerender} = render(
			<DockPresence open smoothness>
				<span>todo</span>
			</DockPresence>,
		);
		expect(screen.getByText('todo')).toBeInTheDocument();
		rerender(
			<DockPresence open={false} smoothness>
				<span>todo</span>
			</DockPresence>,
		);
		expect(screen.getByText('todo')).toBeInTheDocument();
		// 卸载时机必须晚于（而非等于）CSS 过渡结束，否则末帧被截断。
		act(() => {
			vi.advanceTimersByTime(presenceExitMs(cssDurationMs('base')) - 1);
		});
		expect(screen.getByText('todo')).toBeInTheDocument();
		act(() => {
			vi.advanceTimersByTime(1);
		});
		expect(screen.queryByText('todo')).not.toBeInTheDocument();
	});

	// 结构性防漂移：这是 A2 缺陷（180ms 写死 < .xy-dock-presence 的 200ms 过渡）
	// 的直接哨兵。改 tokens.css 的 --duration-base 或改容器过渡时长，二者必须同步增长。
	it('退出延迟严格大于容器过渡时长（末帧不被截断）', () => {
		const containerMs = cssDurationMs('base');
		expect(presenceExitMs(containerMs)).toBeGreaterThan(containerMs);
		expect(presenceExitMs(containerMs) - containerMs).toBe(PRESENCE_EXIT_MARGIN_MS);
	});
});
