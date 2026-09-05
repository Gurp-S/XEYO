import {describe, expect, it} from 'vitest';
import {
	advanceTypewriterShown,
	drainTypewriterStep,
	holdBackPartialListMarker,
	streamTypewriterStepFor,
	structuralTypewriterStep,
	typewriterStep,
} from './useStreamTypewriter';
import {fadeWindowForStep} from '../components/LiveFadeText';

describe('typewriterStep', () => {
	it('reveals one code point when backlog is small', () => {
		expect(typewriterStep(1)).toBe(1);
		expect(typewriterStep(8)).toBe(1);
		expect(typewriterStep(32)).toBe(1);
	});

	it('speeds up gently for medium backlog', () => {
		expect(typewriterStep(33)).toBe(2);
		expect(typewriterStep(56)).toBe(2);
		expect(typewriterStep(57)).toBe(3);
	});

	it('caps catch-up at 6 so the fade tail stays visible', () => {
		expect(typewriterStep(4000)).toBe(6);
	});

	it('no-ops on empty backlog', () => {
		expect(typewriterStep(0)).toBe(0);
	});
});

describe('drainTypewriterStep', () => {
	it('boosts the base curve without dumping a huge burst', () => {
		expect(drainTypewriterStep(32)).toBe(3);
		expect(drainTypewriterStep(4000)).toBe(18);
	});
});

describe('structuralTypewriterStep', () => {
	it('matches the soft live curve (no dump)', () => {
		expect(structuralTypewriterStep(1)).toBe(typewriterStep(1));
		expect(structuralTypewriterStep(4000)).toBe(typewriterStep(4000));
	});
});

describe('streamTypewriterStepFor', () => {
	it('always returns the soft live step', () => {
		const fast = streamTypewriterStepFor('```', () => true);
		expect(fast(1)).toBe(1);
		expect(fast(4000)).toBe(6);
	});
});

describe('holdBackPartialListMarker', () => {
	const hold = (text: string) =>
		holdBackPartialListMarker(Array.from(text), Array.from(text).length);

	it('holds back bare ordered-list markers while the line is incomplete', () => {
		const base = '6. 嘿嘿嘿\n';
		expect(hold('6. 嘿嘿嘿\n7')).toBe(Array.from(base).length);
		expect(hold('6. 嘿嘿嘿\n7.')).toBe(Array.from(base).length);
		expect(hold('6. 嘿嘿嘿\n7. ')).toBe(Array.from(base).length);
	});

	it('releases once the marker has content', () => {
		const text = '6. 嘿嘿嘿\n7. 哈';
		expect(hold(text)).toBe(Array.from(text).length);
	});

	it('releases standalone number lines followed by a newline', () => {
		expect(hold('答案是 42\n')).toBe(Array.from('答案是 42\n').length);
	});

	it('releases numbers that follow text on the same line', () => {
		expect(hold('答案是 42')).toBe(Array.from('答案是 42').length);
	});

	it('releases indented code-like lines and long lines', () => {
		expect(hold('  42')).toBe(Array.from('  42').length);
	});

	it('holds bare unordered markers but not hr rules', () => {
		expect(hold('上一行\n-')).toBe(Array.from('上一行\n').length);
		expect(hold('上一行\n- ')).toBe(Array.from('上一行\n').length);
		expect(hold('上一行\n- 内容')).toBe(Array.from('上一行\n- 内容').length);
		expect(hold('上一行\n---')).toBe(Array.from('上一行\n---').length);
	});

	it('keeps shown a stable prefix and never exposes a bare trailing marker', () => {
		const cache = {full: '', points: [], shown: '', index: 0};
		const full = '6. 嘿嘿嘿\n7. 哈哈哈';
		let shown = '';
		for (let cut = 1; cut <= full.length; cut += 1) {
			const target = full.slice(0, cut);
			let prev = '';
			for (let i = 0; i < 60; i += 1) {
				shown = advanceTypewriterShown(target, shown, cache);
				expect(full.startsWith(shown)).toBe(true);
				// full 在本用例中从不以 7/7. 结尾，揭示结果也不该有该中间态
				expect(shown.endsWith('7')).toBe(false);
				expect(shown.endsWith('7.')).toBe(false);
				if (shown === prev) {
					break;
				}
				prev = shown;
			}
			expect(target.startsWith(shown)).toBe(true);
		}
		expect(shown).toBe(full);
	});
});

describe('fadeWindowForStep', () => {
	it('widens with step so bursts stay inside the fade', () => {
		expect(fadeWindowForStep(1)).toBe(18);
		expect(fadeWindowForStep(2)).toBe(24);
		expect(fadeWindowForStep(6)).toBe(48);
	});
});

describe('advanceTypewriterShown', () => {
	it('stays a prefix of full and advances', () => {
		const next = advanceTypewriterShown('abcdefghij', '');
		expect('abcdefghij'.startsWith(next)).toBe(true);
		expect(next.length).toBeGreaterThan(0);
	});

	it('returns full when already caught up', () => {
		expect(advanceTypewriterShown('hi', 'hi')).toBe('hi');
	});

	it('clears when full is empty', () => {
		expect(advanceTypewriterShown('', 'abc')).toBe('');
	});
});

describe('advanceTypewriterShown cache', () => {
	it('keeps the same reveal sequence for appended text', () => {
		const cache = {full: '', points: [], shown: '', index: 0};
		let shown = '';
		for (const full of ['a', 'ab', 'abc', 'abcd', 'abcde']) {
			shown = advanceTypewriterShown(full, shown, cache);
			expect(full.startsWith(shown)).toBe(true);
		}
		expect(shown).toBe('abcde');
	});

	it('handles an Emoji split across UTF-16 code units', () => {
		const cache = {full: '', points: [], shown: '', index: 0};
		const emoji = 'A😀B';
		let shown = advanceTypewriterShown(emoji.slice(0, 2), '', cache);
		shown = advanceTypewriterShown(emoji.slice(0, 3), shown, cache);
		shown = advanceTypewriterShown(emoji, shown, cache);
		expect(shown).toBe(emoji);
	});

	it('recovers correctly after a non-prefix replacement', () => {
		const cache = {full: '', points: [], shown: '', index: 0};
		const first = advanceTypewriterShown('abcdef', '', cache);
		const replaced = advanceTypewriterShown('xyz', first, cache);
		expect('xyz'.startsWith(replaced)).toBe(true);
	});
});
