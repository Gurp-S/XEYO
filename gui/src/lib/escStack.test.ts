import {afterEach, expect, it, vi} from 'vitest';
import {popEscLayer, pushEscLayer} from './escStack';

afterEach(() => popEscLayer('input-test'));

it.each([{isComposing: true}, {keyCode: 229}])('leaves IME Escape to the input method %j', properties => {
	const stop = vi.fn(); pushEscLayer('input-test', stop);
	const event = new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true, ...properties});
	window.dispatchEvent(event);
	expect(stop).not.toHaveBeenCalled();
	expect(event.defaultPrevented).toBe(false);
});

it('normal Escape invokes only the current layer', () => {
	const stop = vi.fn(); pushEscLayer('input-test', stop);
	const event = new KeyboardEvent('keydown', {key: 'Escape', cancelable: true});
	window.dispatchEvent(event);
	expect(stop).toHaveBeenCalledOnce(); expect(event.defaultPrevented).toBe(true);
});
