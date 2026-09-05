import {afterEach, describe, expect, it, vi} from 'vitest';
import {cancelWhenIdle, runWhenIdle} from '@/lib/idle';

describe('runWhenIdle', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		vi.useRealTimers();
	});

	it('uses requestIdleCallback when present', () => {
		const ric = vi.fn((cb: IdleRequestCallback) => {
			cb({didTimeout: false, timeRemaining: () => 10} as IdleDeadline);
			return 7;
		});
		vi.stubGlobal('requestIdleCallback', ric);
		const fn = vi.fn();
		expect(runWhenIdle(fn)).toBe(7);
		expect(fn).toHaveBeenCalledOnce();
	});

	it('falls back to setTimeout(0)', () => {
		vi.stubGlobal('requestIdleCallback', undefined);
		vi.useFakeTimers();
		const fn = vi.fn();
		runWhenIdle(fn);
		expect(fn).not.toHaveBeenCalled();
		vi.advanceTimersByTime(0);
		expect(fn).toHaveBeenCalledOnce();
	});

	it('cancelWhenIdle prevents the fallback timeout', () => {
		vi.stubGlobal('requestIdleCallback', undefined);
		vi.stubGlobal('cancelIdleCallback', undefined);
		vi.useFakeTimers();
		const fn = vi.fn();
		const id = runWhenIdle(fn);
		cancelWhenIdle(id);
		vi.advanceTimersByTime(0);
		expect(fn).not.toHaveBeenCalled();
	});
});
