/**
 * workspaceReceipt.test.ts — 工作区读写在"200 但读不出"时不得编造内容。
 *
 * 这一族是本项目反复出现的缺陷：客户端把 200 的响应体 `as` 成目标类型直接返回，
 * 缺字段就成了一个"确认过的值"。工作区这条链路的后果最重：
 * - kind=text 而正文不在体里 ⇒ 编辑器显示空文件，用户一按保存就覆盖真实内容；
 * - entries 不在体里 ⇒ 文件树说"这个目录是空的"；
 * - hits 不在体里 ⇒ 搜索说"没有命中"。
 * 三个 parse 函数抛错即可，各 store 已有的 catch 分支会保留旧值并显示错误。
 */
import {describe, expect, it, vi} from 'vitest';
import {
	parseWorkspaceFile,
	parseWorkspaceFileStat,
	parseWorkspaceListing,
	parseWorkspaceSearch,
	readWorkspaceFile,
} from '@/lib/api';

const goodText = {
	cwd: 'D:/proj',
	path: 'a.ts',
	name: 'a.ts',
	mime: 'text/plain',
	size: 4,
	mtime: 1,
	kind: 'text',
	text: 'abcd',
};

describe('工作区文件回执', () => {
	it('形状完整的 text 文件原样通过', () => {
		expect(parseWorkspaceFile(goodText)).toMatchObject({path: 'a.ts', text: 'abcd'});
	});

	it('kind=text 但正文缺失 = 读不出，不是空文件', () => {
		const {text: _drop, ...rest} = goodText;
		expect(() => parseWorkspaceFile(rest)).toThrow(/正文不在回执里/);
	});

	it('kind=image 但没有 data_url = 读不出', () => {
		expect(() =>
			parseWorkspaceFile({...goodText, kind: 'image', text: undefined}),
		).toThrow(/data_url/);
	});

	it('缺 kind / 缺 size 都算读不出', () => {
		expect(() => parseWorkspaceFile({path: 'a', name: 'a', size: 1})).toThrow(/kind/);
		expect(() => parseWorkspaceFile({path: 'a', name: 'a', kind: 'binary'})).toThrow(/path \/ name \/ size/);
	});

	it('不是对象（含数组、null、空串）一律读不出', () => {
		for (const bad of [null, undefined, '""', [], 0]) {
			expect(() => parseWorkspaceFile(bad)).toThrow(/回执不是对象/);
		}
	});

	it('stat 缺 mtime 也算读不出（预览去重靠它）', () => {
		expect(() => parseWorkspaceFileStat({path: 'a', size: 1})).toThrow(/mtime/);
		expect(parseWorkspaceFileStat({path: 'a', name: 'a', size: 1, mtime: 2})).toMatchObject({path: 'a'});
	});
});

describe('目录与搜索回执', () => {
	it('entries 缺失不得变成"空目录"', () => {
		expect(() => parseWorkspaceListing({cwd: 'x', path: '', name: ''})).toThrow(/entries/);
		expect(parseWorkspaceListing({cwd: 'x', path: '', name: '', entries: []})).toMatchObject({});
	});

	it('hits 缺失不得变成"没有命中"', () => {
		expect(() => parseWorkspaceSearch({cwd: 'x', query: 'a'})).toThrow(/hits/);
		expect(parseWorkspaceSearch({cwd: 'x', query: 'a', hits: [], truncated: false})).toMatchObject({});
	});
});

describe('客户端确实走了解析（不是转型完就 return）', () => {
	it('200 + kind=text 无正文 ⇒ 抛错而不是给编辑器一个空文档', async () => {
		const fetchMock = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => ({cwd: 'x', path: 'a.ts', name: 'a.ts', mime: 'text/plain', size: 4, kind: 'text'}),
		});
		vi.stubGlobal('fetch', fetchMock);
		await expect(readWorkspaceFile('a.ts', 'D:/proj')).rejects.toThrow(/正文不在回执里/);
		vi.unstubAllGlobals();
	});
});
