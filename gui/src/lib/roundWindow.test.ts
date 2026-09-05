import {describe, expect, it} from 'vitest';
import {shouldMountRound} from './roundWindow';

describe('round window', () => {
	it('mounts every round when smoothness is off', () => {
		expect(
			shouldMountRound({
				index: 0,
				total: 8,
				smoothness: false,
				ioAvailable: true,
			}),
		).toBe(true);
	});

	it('always mounts the latest two rounds when smoothness is on', () => {
		expect(
			shouldMountRound({
				index: 5,
				total: 8,
				smoothness: true,
				ioAvailable: true,
			}),
		).toBe(false);
		expect(
			shouldMountRound({
				index: 6,
				total: 8,
				smoothness: true,
				ioAvailable: true,
			}),
		).toBe(true);
		expect(
			shouldMountRound({
				index: 7,
				total: 8,
				smoothness: true,
				ioAvailable: true,
			}),
		).toBe(true);
	});

	it('mounts all when IntersectionObserver is unavailable', () => {
		expect(
			shouldMountRound({
				index: 0,
				total: 8,
				smoothness: true,
				ioAvailable: false,
			}),
		).toBe(true);
	});
});
