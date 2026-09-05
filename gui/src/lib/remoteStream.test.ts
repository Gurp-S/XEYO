import {describe, expect, it} from 'vitest';
import {assembleStream} from './remoteStream';

describe('assembleStream', () => {
	it('appends a suffix from stream_from', () => {
		const a = assembleStream({
			acc: 'hello',
			from: 5,
			chunk: ' world',
			serverLen: 11,
		});
		expect(a.acc).toBe('hello world');
		expect(a.from).toBe(11);
	});

	it('replaces on reset or stale from', () => {
		const reset = assembleStream({
			acc: 'old',
			from: 3,
			chunk: 'new',
			serverLen: 3,
			reset: true,
		});
		expect(reset.acc).toBe('new');
		const stale = assembleStream({
			acc: 'hello world',
			from: 20,
			chunk: 'hi',
			serverLen: 2,
		});
		expect(stale.acc).toBe('hi');
		expect(stale.from).toBe(2);
	});

	it('starts from empty acc', () => {
		const a = assembleStream({
			acc: '',
			from: 0,
			chunk: 'ab',
			serverLen: 2,
		});
		expect(a.acc).toBe('ab');
	});
});
