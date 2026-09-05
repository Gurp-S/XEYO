import {describe, expect, it} from 'vitest';
import {
	formatSlashHelp,
	parseSlashInput,
	slashLeadingColor,
	slashSuggestions,
	slashTokenAt,
} from '@/lib/slash';
import {slashCommands} from '@/generated/slashManifest';

describe('slash manifest (generated)', () => {
	it('exposes the unified command table', () => {
		expect(slashCommands.length).toBeGreaterThanOrEqual(30);
		const names = new Set(slashCommands.map(c => c.name));
		for (const required of [
			'help', 'version', 'status', 'usage', 'context', 'cwd', 'clear',
			'transcript', 'export', 'retry', 'mode', 'output', 'code', 'model',
			'theme', 'approval', 'stop', 'allow', 'deny', 'compact', 'run',
			'git', 'diff', 'revert', 'skills', 'mcp', 'plugins',
		]) {
			expect(names.has(required)).toBe(true);
		}
	});
	it('keeps aliases unique across commands', () => {
		const seen = new Set<string>();
		for (const c of slashCommands) {
			for (const a of c.aliases) {
				expect(seen.has(a)).toBe(false);
				seen.add(a);
			}
		}
	});
});

describe('parseSlashInput', () => {
	it('treats plain text as non-slash', () => {
		expect(parseSlashInput('帮我看看 main.py').isSlash).toBe(false);
	});
	it('parses known command with args', () => {
		const r = parseSlashInput('/mode plan');
		expect(r.isSlash).toBe(true);
		expect(r.command?.name).toBe('mode');
		expect(r.arg).toBe('plan');
		expect(r.unknown).toBe(false);
	});
	it('parses chinese aliases', () => {
		expect(parseSlashInput('/目录').command?.name).toBe('cwd');
		expect(parseSlashInput('/历史 5').command?.name).toBe('transcript');
		expect(parseSlashInput('/压缩').command?.name).toBe('compact');
	});
	it('flags unknown slash input', () => {
		const r = parseSlashInput('/nope x');
		expect(r.isSlash).toBe(true);
		expect(r.unknown).toBe(true);
		expect(r.name).toBe('nope');
		expect(r.arg).toBe('x');
	});
	it('hides commands not available on gui surface', () => {
		// /exit 只在 CLI；GUI 输入 /exit 应视为未知（不误吞）
		const r = parseSlashInput('/exit');
		expect(r.unknown).toBe(true);
	});
});

describe('slashSuggestions', () => {
	it('suggests by name and chinese alias prefix', () => {
		const byName = slashSuggestions('/co').map(c => c.name);
		expect(byName).toContain('code');
		expect(byName).toContain('compact');
		expect(byName).toContain('context');
		const byAlias = slashSuggestions('/目录');
		expect(byAlias.some(c => c.name === 'cwd')).toBe(true);
	});
	it('returns empty for non-slash or spaced input', () => {
		expect(slashSuggestions('hello')).toHaveLength(0);
		expect(slashSuggestions('/mode plan')).toHaveLength(0);
	});
});

describe('slashTokenAt', () => {
	it('detects token at start of input', () => {
		expect(slashTokenAt('/he', 3)).toEqual({text: '/he', start: 0, end: 3});
		expect(slashTokenAt('/', 1)).toEqual({text: '/', start: 0, end: 1});
	});
	it('detects token after whitespace mid-text', () => {
		expect(slashTokenAt('帮我 /sk', 6)).toEqual({text: '/sk', start: 3, end: 6});
		expect(slashTokenAt('a\n/s', 4)).toEqual({text: '/s', start: 2, end: 4});
	});
	it('extends token when caret sits mid-word', () => {
		expect(slashTokenAt('/skip', 4)).toEqual({text: '/skip', start: 0, end: 5});
	});
	it('returns null for non-slash contexts', () => {
		expect(slashTokenAt('hello', 5)).toBeNull();
		expect(slashTokenAt('hello ', 6)).toBeNull();
		expect(slashTokenAt('', 0)).toBeNull();
	});
	it('does not trigger inside urls or paths', () => {
		expect(slashTokenAt('https://example.com', 19)).toBeNull();
		expect(slashTokenAt('src/foo.ts', 10)).toBeNull();
	});
	it('rejects out-of-range caret', () => {
		expect(slashTokenAt('/ab', 9)).toBeNull();
		expect(slashTokenAt('/ab', -1)).toBeNull();
	});
});

describe('slashLeadingColor', () => {
	const skills = [{name: 'archify'}, {name: 'web-search'}];
	it('colors exact gui commands as command', () => {
		expect(slashLeadingColor('help', skills)).toBe('command');
		expect(slashLeadingColor('skills', skills)).toBe('command');
		expect(slashLeadingColor('目录', skills)).toBe('command');
		expect(slashLeadingColor('SKILLS', skills)).toBe('command');
	});
	it('colors exact skill names as skill', () => {
		expect(slashLeadingColor('archify', skills)).toBe('skill');
		expect(slashLeadingColor('Web-Search', skills)).toBe('skill');
	});
	it('colors prefixes while typing', () => {
		expect(slashLeadingColor('he', skills)).toBe('command');
		expect(slashLeadingColor('web', skills)).toBe('skill');
	});
	it('prefers exact skill over prefix command', () => {
		expect(slashLeadingColor('he', [{name: 'he'}])).toBe('skill');
	});
	it('returns null for unknown or empty head', () => {
		expect(slashLeadingColor('zzz', skills)).toBeNull();
		expect(slashLeadingColor('', skills)).toBeNull();
		expect(slashLeadingColor('usr/bin', skills)).toBeNull();
	});
});

describe('formatSlashHelp', () => {
	it('groups gui commands and hides cli-only ones', () => {
		const help = formatSlashHelp();
		expect(help).toContain('/help');
		expect(help).toContain('/theme');
		expect(help).not.toContain('/exit');
		expect(help).toContain('● ');
	});
});
