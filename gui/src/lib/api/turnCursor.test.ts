import {beforeEach, describe, expect, it} from 'vitest';
import {readTurnCursor, rememberTurnCursor} from './turnCursor';

beforeEach(() => sessionStorage.clear());
describe('detached turn cursors', () => {
	it('a new automatic turn starts from zero rather than inheriting a prior turn cursor', () => {
		rememberTurnCursor('s1', 700, 'turn-1');
		expect(readTurnCursor('s1', 'turn-1')).toBe(700);
		expect(readTurnCursor('s1', 'turn-2')).toBe(0);
		rememberTurnCursor('s1', 2, 'turn-2');
		expect(readTurnCursor('s1', 'turn-2')).toBe(2);
		expect(readTurnCursor('s1', 'turn-1')).toBe(0);
	});
	it('unscoped legacy storage cannot suppress a newly identified turn', () => {
		sessionStorage.setItem('xeyo:turnCursor:s1', '700');
		expect(readTurnCursor('s1', 'turn-2')).toBe(0);
		rememberTurnCursor('s1', 0);
		expect(readTurnCursor('s1')).toBe(0);
	});
});
