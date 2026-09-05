import {act, cleanup, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
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
		act(() => {
			vi.advanceTimersByTime(200);
		});
		expect(screen.queryByText('todo')).not.toBeInTheDocument();
	});
});
