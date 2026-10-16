import {describe, expect, it} from 'vitest';
import {advanceTypewriterShown} from '@/hooks/useStreamTypewriter';
import {createStreamReveal, STREAM_REVEAL_MS} from './streamReveal';

describe('time bounded stream reveal', () => {
	it.each([30, 60, 120, 144])('finishes a burst within the time budget at %i Hz', hz => {
		let time = 0;
		const step = createStreamReveal(STREAM_REVEAL_MS, () => time);
		const full = '正文😀\n```ts\nconst n = 1;\n```\n'.repeat(300);
		const cache = {full: '', points: [], shown: '', index: 0};
		let shown = advanceTypewriterShown(full, '', cache, step, false);
		let frames = 0;
		while (shown !== full && time < 1000) {
			time += 1000 / hz;
			const next = advanceTypewriterShown(full, shown, cache, step, false);
			expect(next.startsWith(shown)).toBe(true);
			expect(full.startsWith(next)).toBe(true);
			shown = next;
			frames++;
		}
		expect(shown).toBe(full);
		expect(frames).toBeGreaterThan(1);
		expect(time).toBeLessThanOrEqual(STREAM_REVEAL_MS + 1000 / hz + 1);
	});

	it('bounds lag during continuous appends instead of moving the deadline', () => {
		let time = 0;
		const step = createStreamReveal(STREAM_REVEAL_MS, () => time);
		let shown = 0;
		for (; time <= 2000; time += 10) {
			const received = time * 20 + 100;
			shown += step(received - shown, shown);
			expect(received - shown).toBeLessThanOrEqual(2 * STREAM_REVEAL_MS * 20 + 100);
		}
	});

	it('does not spend another frame budget when called twice at the same time', () => {
		let time = 0;
		const step = createStreamReveal(STREAM_REVEAL_MS, () => time);
		expect(step(1000, 0)).toBe(1);
		time = 25;
		const amount = step(1000, 0);
		expect(amount).toBeGreaterThan(0);
		expect(step(1000 - amount, amount)).toBe(0);
	});

	it('recovers after a tool boundary and releases a final bare list marker', () => {
		let time = 0;
		const step = createStreamReveal(STREAM_REVEAL_MS, () => time);
		const cache = {full: '', points: [], shown: '', index: 0};
		advanceTypewriterShown('old text'.repeat(50), '', cache, step);
		time = 40;
		advanceTypewriterShown('', '', cache, step);
		let shown = advanceTypewriterShown('新答案😀\n7. ', '', cache, step);
		time += STREAM_REVEAL_MS;
		shown = advanceTypewriterShown('新答案😀\n7. ', shown, cache, step);
		expect(shown).toBe('新答案😀\n');
		expect(advanceTypewriterShown('新答案😀\n7. ', shown, cache, step, false)).toBe('新答案😀\n7. ');
	});
});
