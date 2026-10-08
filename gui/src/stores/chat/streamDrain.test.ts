import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {createStreamDrain} from './streamDrain';
import {activeDrains, type ChatState} from './preStoreHelpers';

let frames: Array<FrameRequestCallback>;
beforeEach(() => {
	activeDrains.clear(); frames = [];
	vi.stubGlobal('requestAnimationFrame', vi.fn(callback => {frames.push(callback); return frames.length;}));
	vi.stubGlobal('cancelAnimationFrame', vi.fn());
});
afterEach(() => {activeDrains.clear(); vi.unstubAllGlobals();});

function fixture() {
	let state = {activeId: null, messagesById: {gui: []}, sessionTodosById: {},
		sessionStreams: {gui: {streamingText: 'old response', streamingShown: ''}},
	} as unknown as ChatState;
	const get = () => state;
	const set: Parameters<typeof createStreamDrain>[0]['set'] = update => {
		state = {...state, ...typeof update === 'function' ? update(state) : update};
	};
	let alive = true; const finish = vi.fn();
	const make = () => createStreamDrain({get, set, sessionId: 'gui', typewriterCache: {full: '', points: [], shown: '', index: 0},
		persistNow: vi.fn(), sessionStillAlive: () => alive, cancelFrameRaf: vi.fn(), onFinish: finish});
	return {get, set, make, finish, expire: () => {alive = false;}};
}

it('an expired drain frame cannot advance or settle a newer turn', () => {
	const f = fixture(); const old = f.make(); old.start(); const frame = frames[0]!;
	f.expire(); f.set({sessionStreams: {gui: {streamingText: 'NEW RESPONSE', streamingShown: '', isLoading: true}} as never});
	frame(0);
	expect(f.get().sessionStreams.gui?.streamingShown).toBe('');
	expect(f.finish).not.toHaveBeenCalled();
	expect(activeDrains.has('gui')).toBe(false);
});

it.each(['finish', 'discard'] as const)('old %s cannot release a replacement drain', action => {
	const f = fixture(); const old = f.make(); old.start(); const current = f.make(); current.start();
	const owner = activeDrains.get('gui'); const before = f.get(); old[action]();
	expect(activeDrains.get('gui')).toBe(owner);
	expect(f.get()).toBe(before);
	expect(f.finish).not.toHaveBeenCalled();
});

it('a current drain finishes and releases its own registration', () => {
	const f = fixture(); const drain = f.make(); drain.start(); drain.finish();
	expect(f.finish).toHaveBeenCalledOnce(); expect(activeDrains.has('gui')).toBe(false);
});
