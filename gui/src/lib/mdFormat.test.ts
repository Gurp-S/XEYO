import {describe, expect, it} from 'vitest';
import {applyMdFormat, wrapMarkdownSelection} from './mdFormat';

describe('wrapMarkdownSelection', () => {
	it('wraps inline marks', () => {
		expect(wrapMarkdownSelection('hi', 'bold')).toBe('**hi**');
		expect(wrapMarkdownSelection('hi', 'italic')).toBe('*hi*');
		expect(wrapMarkdownSelection('hi', 'strike')).toBe('~~hi~~');
		expect(wrapMarkdownSelection('hi', 'underline')).toBe('<u>hi</u>');
		expect(wrapMarkdownSelection('hi', 'code')).toBe('`hi`');
		expect(wrapMarkdownSelection('hi', 'link', 'https://x.dev')).toBe(
			'[hi](https://x.dev)',
		);
	});

	it('prefixes list and quote lines', () => {
		expect(wrapMarkdownSelection('a\nb', 'ul')).toBe('- a\n- b');
		expect(wrapMarkdownSelection('a\nb', 'ol')).toBe('1. a\n2. b');
		expect(wrapMarkdownSelection('a\nb', 'quote')).toBe('> a\n> b');
	});
});

describe('applyMdFormat', () => {
	it('replaces the first occurrence in source', () => {
		const next = applyMdFormat('# title\n\nhello world\n', 'hello', 'bold');
		expect(next).toBe('# title\n\n**hello** world\n');
	});

	it('toggles the same inline mark off', () => {
		expect(applyMdFormat('say **hi** now', 'hi', 'bold')).toBe('say hi now');
		expect(applyMdFormat('say *hi* now', 'hi', 'italic')).toBe('say hi now');
		expect(applyMdFormat('say <u>hi</u> now', 'hi', 'underline')).toBe(
			'say hi now',
		);
		expect(applyMdFormat('say ~~hi~~ now', 'hi', 'strike')).toBe('say hi now');
		expect(applyMdFormat('say `hi` now', 'hi', 'code')).toBe('say hi now');
	});

	it('does not treat bold stars as italic', () => {
		expect(applyMdFormat('**hi**', 'hi', 'italic')).toBe('***hi***');
	});

	it('toggles list and quote prefixes', () => {
		expect(applyMdFormat('- a\n- b', '- a\n- b', 'ul')).toBe('a\nb');
		expect(applyMdFormat('> a\n> b', '> a\n> b', 'quote')).toBe('a\nb');
	});

	it('maps a rendered phrase that spans marks', () => {
		expect(applyMdFormat('**hello** world', 'hello world', 'strike')).not.toBeNull();
	});

	it('returns null when the selection is not in source', () => {
		expect(applyMdFormat('# title', 'missing', 'italic')).toBeNull();
		expect(applyMdFormat('# title', '', 'bold')).toBeNull();
	});
});
