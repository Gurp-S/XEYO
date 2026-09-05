import {describe, expect, it} from 'vitest';
import {roundStreamHostProps} from './useMessageListStore';

describe('roundStreamHostProps', () => {
	const live = {
		roundSettled: false,
		streamingSignal: true,
		thoughtStartedAt: 100,
		latestTurnId: 'turn-9',
	};

	it('passes live stream props to the latest round only', () => {
		expect(roundStreamHostProps(2, 2, live)).toEqual(live);
	});

	it('freezes stream props for historical rounds', () => {
		expect(roundStreamHostProps(0, 2, live)).toEqual({
			roundSettled: true,
			streamingSignal: false,
			thoughtStartedAt: null,
			latestTurnId: null,
		});
	});
});
