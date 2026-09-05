import {describe, expect, it} from 'vitest';
import {fadeWindowForStep} from './LiveFadeText';

describe('fadeWindowForStep', () => {
	it('grows with typing step and caps at 48', () => {
		expect(fadeWindowForStep(1)).toBe(18);
		expect(fadeWindowForStep(3)).toBe(30);
		expect(fadeWindowForStep(20)).toBe(48);
	});
});
