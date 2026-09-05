import {act, cleanup, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {MorphVerb} from './MorphVerb';

describe('MorphVerb A8', () => {
	afterEach(() => {
		cleanup();
		vi.useRealTimers();
	});

	it('crossfades Reading → Read with leave + enter layers', () => {
		vi.useFakeTimers();
		const {rerender} = render(<MorphVerb verb="Reading" />);
		expect(screen.getByText('Reading')).toBeTruthy();

		rerender(<MorphVerb verb="Read" />);
		expect(screen.getByText('Reading')).toBeTruthy();
		expect(screen.getByText('Read')).toBeTruthy();
		expect(document.querySelector('.xy-morph .is-leave')?.textContent).toBe(
			'Reading',
		);
		expect(document.querySelector('.xy-morph .is-enter')?.textContent).toBe(
			'Read',
		);

		act(() => {
			vi.advanceTimersByTime(360);
		});
		expect(screen.queryByText('Reading')).toBeNull();
		expect(screen.getByText('Read')).toBeTruthy();
	});
});
