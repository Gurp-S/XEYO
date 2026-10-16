import {afterEach, describe, expect, it, vi} from 'vitest';
import {waitForDesktopBackend} from './desktopStartup';

afterEach(() => vi.useRealTimers());
describe('desktop startup readiness', () => {
	it('waits for readiness before releasing hydration', async () => {
		vi.useFakeTimers();
		const read = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(false).mockResolvedValue(true);
		const mounted = vi.fn();
		const pending = waitForDesktopBackend(read, new AbortController().signal).then(mounted);
		await vi.advanceTimersByTimeAsync(399); expect(mounted).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1); await pending;
		expect(mounted).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
	});
	it('close cancels waiting and removes timers', async () => {
		vi.useFakeTimers(); const controller = new AbortController();
		const pending = waitForDesktopBackend(vi.fn().mockResolvedValue(false), controller.signal);
		const rejected = expect(pending).rejects.toMatchObject({name:'AbortError'});
		await vi.advanceTimersByTimeAsync(0); controller.abort(); await rejected;
		expect(vi.getTimerCount()).toBe(0);
	});
	it('propagates startup failure for the visible retry state', async () => {
		await expect(waitForDesktopBackend(() => Promise.reject(new Error('missing runtime')), new AbortController().signal)).rejects.toThrow('missing runtime');
	});
});
