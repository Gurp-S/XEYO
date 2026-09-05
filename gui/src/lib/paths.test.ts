import {describe, expect, it} from 'vitest';
import {folderName, joinFsPath, looksLikeFsPath, normalizePath, parentDir, samePath} from './paths';

describe('paths', () => {
	it('normalizes windows separators and case', () => {
		expect(normalizePath('D:\\Foo\\Bar\\')).toBe('d:/foo/bar');
		expect(samePath('D:\\Foo\\Bar', 'd:/foo/bar/')).toBe(true);
	});

	it('strips extended-length prefix', () => {
		expect(samePath('\\\\?\\D:\\proj\\xyai', 'D:\\proj\\xyai')).toBe(true);
		expect(samePath('//?/D:/proj/xyai', 'D:/proj/xyai')).toBe(true);
	});

	it('folderName uses basename', () => {
		expect(folderName('D:\\lea\\xyai')).toBe('xyai');
		expect(folderName('D:\\lea\\xyai\\')).toBe('xyai');
	});

	it('joinFsPath keeps windows separators', () => {
		expect(joinFsPath('D:\\lea', 'xyai')).toBe('D:\\lea\\xyai');
		expect(joinFsPath('D:\\lea\\', 'xyai')).toBe('D:\\lea\\xyai');
	});

	it('parentDir returns parent and drive root', () => {
		expect(parentDir('D:\\lea\\xyai')).toBe('D:\\lea');
		expect(parentDir('D:\\lea')).toBe('D:\\');
	});

	it('looksLikeFsPath detects absolute windows paths', () => {
		expect(looksLikeFsPath('D:\\lea\\xyai')).toBe(true);
		expect(looksLikeFsPath('owner/repo')).toBe(false);
	});
});
