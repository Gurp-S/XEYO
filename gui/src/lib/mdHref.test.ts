import {describe, expect, it} from 'vitest';
import {joinWorkspace, resolveMdHref} from './mdHref';

describe('joinWorkspace', () => {
	it('resolves sibling and parent paths', () => {
		expect(joinWorkspace('docs/设计/10-完整记忆体系.md', './09-企业级落地计划-时序与排期.md')).toBe(
			'docs/设计/09-企业级落地计划-时序与排期.md',
		);
		expect(joinWorkspace('docs/a.md', '../python/x.py')).toBe('python/x.py');
	});
});

describe('resolveMdHref', () => {
	it('keeps http and blocks javascript', () => {
		expect(resolveMdHref('https://example.com')).toEqual({
			kind: 'external',
			href: 'https://example.com',
		});
		expect(resolveMdHref('javascript:alert(1)')).toEqual({kind: 'unsafe'});
	});

	it('parses hash and local wiki links', () => {
		expect(resolveMdHref('#sec')).toEqual({kind: 'hash', id: 'sec'});
		expect(
			resolveMdHref('./09-x.md#s', 'docs/10.md'),
		).toEqual({kind: 'local', path: 'docs/09-x.md', hash: 's'});
		expect(
			resolveMdHref('./09-%E4%BC%81.md', 'docs/10.md'),
		).toEqual({kind: 'local', path: 'docs/09-企.md'});
	});
});
