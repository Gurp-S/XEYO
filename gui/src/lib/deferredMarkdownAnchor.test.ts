import {describe, expect, it, vi} from 'vitest';
import {followDeferredMarkdownAnchor} from './deferredMarkdownAnchor';

describe('deferred Markdown anchors', () => {
	it('finds a heading inserted after the initial timer, within this document only', async () => {
		vi.useFakeTimers();
		const root = document.createElement('div');
		const dispose = followDeferredMarkdownAnchor(root, 'target');
		await vi.advanceTimersByTimeAsync(80);
		const heading = document.createElement('h2'); heading.id = 'target';
		heading.scrollIntoView = vi.fn(); root.append(heading);
		await Promise.resolve();
		expect(heading.scrollIntoView).toHaveBeenCalledOnce();
		root.append(document.createElement('p')); await Promise.resolve();
		expect(heading.scrollIntoView).toHaveBeenCalledOnce();
		dispose(); vi.useRealTimers();
	});
	it('cancels pending jumps when the file changes or closes', async () => {
		const root = document.createElement('div');
		const dispose = followDeferredMarkdownAnchor(root, 'target'); dispose();
		const heading = document.createElement('h2'); heading.id = 'target'; heading.scrollIntoView = vi.fn();
		root.append(heading); await Promise.resolve();
		expect(heading.scrollIntoView).not.toHaveBeenCalled();
	});
});
