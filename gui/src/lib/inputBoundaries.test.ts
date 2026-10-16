import {describe, expect, it} from 'vitest';
import {joinFsPath, normalizePath, parentDir, samePath, uniqueParentDirs} from './paths';
import {normalizeWindowLimit, resolveWindowLimit, windowUsagePercent} from './modelWindow';

describe('本地路径的根目录边界', () => {
	it.each([
		['/', 'tmp', '/tmp'],
		['/tmp/', 'file.txt', '/tmp/file.txt'],
		['C:\\', 'file.txt', 'C:\\file.txt'],
		['\\\\server\\share\\', 'file.txt', '\\\\server\\share\\file.txt'],
	])('拼接 %s 与 %s 保留根目录', (parent, child, expected) => {
		expect(joinFsPath(parent, child)).toBe(expected);
	});

	it.each([
		['/', '/'],
		['/tmp', '/'],
		['/tmp/file.txt', '/tmp'],
		['C:\\', 'C:\\'],
		['C:/', 'C:/'],
		['C:\\tmp', 'C:\\'],
		['\\\\server\\share', '\\\\server\\share'],
		['\\\\server\\share\\dir', '\\\\server\\share\\'],
		['\\\\?\\UNC\\server\\share\\dir', '\\\\?\\UNC\\server\\share\\'],
		['relative/file.txt', 'relative'],
	])('父目录 %s 保留文件系统根', (path, expected) => {
		expect(parentDir(path)).toBe(expected);
	});

	it('POSIX 根有有效的比较键，并可出现在去重后的父目录列表中', () => {
		expect(normalizePath('/')).toBe('/');
		expect(samePath('/', '/')).toBe(true);
		expect(uniqueParentDirs(['/a', '/b', '/tmp/c'])).toEqual(['/', '/tmp']);
	});

	it('扩展 UNC 路径与普通 UNC 路径指向同一共享', () => {
		expect(samePath('\\\\?\\UNC\\server\\share\\dir', '\\\\server\\share\\dir')).toBe(true);
		expect(samePath('\\\\server\\share', '/server/share')).toBe(false);
	});
});

describe('模型窗口的数值边界', () => {
	it.each([undefined, null, '100', true, NaN, Infinity, -Infinity, -1, 0, 0.1, 0.99])(
		'无效窗口 %s 不会归一化为零分母', value => {
			expect(normalizeWindowLimit(value)).toBeUndefined();
		},
	);

	it('有效小数窗口保持已有的向下取整行为', () => {
		expect(normalizeWindowLimit(128.9)).toBe(128);
	});

	it('无效的设置值继续回退到厂商窗口', () => {
		expect(resolveWindowLimit({registered: 0.5, vendorCached: 128_000})).toBe(128_000);
	});

	it('无效窗口不产生 NaN 或虚假的百分之百占用', () => {
		expect(windowUsagePercent({contextTokens: 0, limit: 0.5})).toBeUndefined();
		expect(windowUsagePercent({contextTokens: 1, limit: 0.5})).toBeUndefined();
	});
});
