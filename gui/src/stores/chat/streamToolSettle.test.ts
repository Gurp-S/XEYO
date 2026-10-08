import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {createToolSettleController} from './streamToolSettle';
import {waitingToolTimers, WAITING_TOOL_TIMEOUT_MS} from './streamHelpers';
import type {ChatState} from './preStoreHelpers';
import type {ChatMessage} from '@/lib/types';

const replace = vi.hoisted(() => vi.fn());
vi.mock('@/lib/db', async original => ({...await original<typeof import('@/lib/db')>(), replaceMessages: replace}));
beforeEach(() => {vi.useFakeTimers(); vi.resetAllMocks(); waitingToolTimers.clear();});
afterEach(() => {vi.useRealTimers(); waitingToolTimers.clear();});

const tool = (id: string, status: 'waiting' | 'running'): ChatMessage => ({id, role: 'tool', text: '', createdAt: 1, toolStatus: status});
function fixture() {
	let currentOwner = true;
	let state = {sessions: [{id: 'gui'}], messagesById: {gui: [tool('old', 'waiting')]}, sessionTodosById: {}} as unknown as ChatState;
	const get = () => state;
	const set: Parameters<typeof createToolSettleController>[0]['set'] = update => {state = {...state, ...typeof update === 'function' ? update(state) : update};};
	const controller = createToolSettleController({get, set, sessionId: 'gui', persistNow: vi.fn(), applyToolResult: vi.fn(), isCurrent: () => currentOwner});
	return {get, set, controller, expire: () => {currentOwner = false;}};
}

it('a waiting timeout does not settle a later running tool', () => {
	const f = fixture(); f.controller.scheduleWaitingToolSettle();
	const current = tool('new', 'running'); f.set({messagesById: {gui: [...f.get().messagesById.gui!, current]}});
	vi.advanceTimersByTime(WAITING_TOOL_TIMEOUT_MS);
	expect(f.get().messagesById.gui?.[0]?.toolStatus).toBe('error');
	expect(f.get().messagesById.gui?.[1]).toBe(current);
});

it('an expired timeout cannot write a later turn to IDB', () => {
	const f = fixture(); f.controller.scheduleWaitingToolSettle(); f.expire();
	const before = f.get(); vi.advanceTimersByTime(WAITING_TOOL_TIMEOUT_MS);
	expect(f.get()).toBe(before); expect(replace).not.toHaveBeenCalled();
});

it('an expired timeout does not remove the registration of a replacement timer', () => {
	const f = fixture(); f.controller.scheduleWaitingToolSettle();
	waitingToolTimers.set('gui', 987654);
	vi.advanceTimersByTime(WAITING_TOOL_TIMEOUT_MS);
	expect(waitingToolTimers.get('gui')).toBe(987654); expect(replace).not.toHaveBeenCalled();
});
