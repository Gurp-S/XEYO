import {describe, expect, it} from 'vitest';
import {
	cloneDestPath,
	expandGitUrl,
	isValidFolderName,
	repoNameFromGitUrl,
} from './workspaceAdd';

describe('workspaceAdd', () => {
	it('accepts simple folder names and rejects path fragments', () => {
		expect(isValidFolderName('my-app')).toBe(true);
		expect(isValidFolderName('foo/bar')).toBe(false);
		expect(isValidFolderName('..')).toBe(false);
		expect(isValidFolderName('a:b')).toBe(false);
	});

	it('expands GitHub shorthand and keeps full URLs', () => {
		expect(expandGitUrl('owner/repo')).toBe('https://github.com/owner/repo.git');
		expect(expandGitUrl('https://github.com/owner/repo.git')).toBe(
			'https://github.com/owner/repo.git',
		);
		expect(expandGitUrl('not a url')).toBeNull();
	});

	it('parses repo folder name from git URL', () => {
		expect(repoNameFromGitUrl('https://github.com/owner/xyai.git')).toBe('xyai');
		expect(repoNameFromGitUrl('git@github.com:owner/xyai.git')).toBe('xyai');
	});

	it('builds clone destination under the picked parent', () => {
		expect(cloneDestPath('D:\\lea', 'https://github.com/owner/xyai.git')).toBe(
			'D:\\lea\\xyai',
		);
	});
});
