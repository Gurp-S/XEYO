import {describe, expect, it} from 'vitest';
import {fileExt, highlightLangForName, isMarkdownName} from './fileKind';

describe('fileKind', () => {
	it('detects markdown and code languages', () => {
		expect(isMarkdownName('README.md')).toBe(true);
		expect(isMarkdownName('note.MDX')).toBe(true);
		expect(isMarkdownName('app.ts')).toBe(false);
		expect(highlightLangForName('main.py')).toBe('python');
		expect(highlightLangForName('App.tsx')).toBe('tsx');
		expect(fileExt('.gitignore')).toBe('');
	});
});
