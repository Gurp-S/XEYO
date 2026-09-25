/**
 * mapReceipt.test.ts — 工作区地图不得把"200 但读不出"说成完整或没有。
 *
 * 地图三个只读接口的真失败走 HTTP 状态码，客户端于是从不看响应体。
 * 缺字段的 200 过去会：`truncated` 缺失 ⇒ 面板只说「N 个文件」而不带"（已截断）"，
 * 把残缺的图说成完整；`fileCount` 缺失 ⇒ 印成「undefined 个文件」；
 * `files` 缺失 ⇒ 卡片详情里 `graph.files.find` 当场抛（那一处连 ? 都没写）；
 * `symbols` 缺失 / `summary` 缺失 ⇒ 说成"这个文件没有符号""（无摘要）"。
 * 形体取自 python/codeindex/graph.py 与 server/routers/workspace.py 的真实返回。
 */
import {describe, expect, it, vi} from 'vitest';
import {
	explainMapNode,
	fetchWorkspaceGraph,
	fetchWorkspaceOutline,
	parseMapExplain,
	parseWorkspaceGraph,
	parseWorkspaceOutline,
} from '@/lib/workspaceMapApi';

const goodGraph = {
	ok: true,
	cwd: 'D:/proj',
	fileCount: 2,
	truncated: false,
	layers: ['core'],
	files: [
		{id: 'a.ts', name: 'a.ts', layer: 'core', pkg: '.'},
		{id: 'b.ts', name: 'b.ts', layer: 'core', pkg: '.'},
	],
	fileEdges: [{from: 'a.ts', to: 'b.ts'}],
	packages: [{id: '.', name: '.', layer: 'core', files: 2}],
	packageEdges: [],
};

const goodOutline = {
	ok: true,
	cwd: 'D:/proj',
	path: 'a.ts',
	symbols: [
		{kind: 'function', name: 'run', start: 1, end: 9, parent: null, signature: 'run()', approximate: false},
	],
};

const goodExplain = {
	ok: true,
	cwd: 'D:/proj',
	id: 'a.ts',
	kind: 'file',
	summary: '文件 `a.ts` · 层 core · 包 .',
	source: 'structure',
};

function stubJson(payload: unknown) {
	return vi.fn().mockResolvedValue({ok: true, status: 200, json: async () => payload});
}

describe('地图回执', () => {
	it('完整图原样通过；空边表是合法事实，不该拦', () => {
		expect(parseWorkspaceGraph(goodGraph)).toMatchObject({fileCount: 2});
		expect(parseWorkspaceGraph({...goodGraph, fileEdges: [], packageEdges: [], layers: []})).toMatchObject({});
	});

	it('缺 truncated ⇒ 不能说这张图是完整的', () => {
		const {truncated: _drop, ...rest} = goodGraph;
		expect(() => parseWorkspaceGraph(rest)).toThrow(/fileCount \/ truncated/);
	});

	it('缺 fileCount ⇒ 不能印成"undefined 个文件"', () => {
		expect(() => parseWorkspaceGraph({...goodGraph, fileCount: undefined})).toThrow(/fileCount \/ truncated/);
	});

	it('缺 files / packages ⇒ 读不出不等于这个工作区没有文件、没有包', () => {
		const {files: _a, ...noFiles} = goodGraph;
		expect(() => parseWorkspaceGraph(noFiles)).toThrow(/回执缺 files/);
		const {packages: _b, ...noPkgs} = goodGraph;
		expect(() => parseWorkspaceGraph(noPkgs)).toThrow(/回执缺 packages/);
	});

	it('缺 layers ⇒ 分层轴无从生成', () => {
		const {layers: _drop, ...rest} = goodGraph;
		expect(() => parseWorkspaceGraph(rest)).toThrow(/回执缺 layers/);
	});
});

describe('符号大纲与节点说明回执', () => {
	it('symbols 缺失或夹了非符号条目 ⇒ 读不出，不是"这个文件没有符号"', () => {
		expect(parseWorkspaceOutline({...goodOutline, symbols: []})).toMatchObject({path: 'a.ts'});
		const {symbols: _drop, ...rest} = goodOutline;
		expect(() => parseWorkspaceOutline(rest)).toThrow(/回执缺 symbols/);
		expect(() => parseWorkspaceOutline({...goodOutline, symbols: ['run']})).toThrow(/不是符号/);
	});

	it('summary 缺失 ⇒ 读不出，不是"这个节点没有说明"', () => {
		expect(() => parseMapExplain({...goodExplain, summary: undefined})).toThrow(/没有说明/);
		expect(parseMapExplain(goodExplain)).toMatchObject({source: 'structure'});
	});

	it('非对象回执一律读不出', () => {
		for (const bad of [null, undefined, 'x', [], 0]) {
			expect(() => parseWorkspaceGraph(bad)).toThrow(/回执不是对象/);
			expect(() => parseWorkspaceOutline(bad)).toThrow(/回执不是对象/);
			expect(() => parseMapExplain(bad)).toThrow(/回执不是对象/);
		}
	});

	// 三份回执的 `ok` 都必须是布尔：它是"后端怎么说自己"这一栏，
	// 不在体里就说明响应体压根不是这个接口的回执（反代页 / 登录页转 JSON 等）。
	it('缺 ok ⇒ 三份回执都读不出', () => {
		expect(() => parseWorkspaceGraph({...goodGraph, ok: undefined})).toThrow(/回执缺 ok/);
		expect(() => parseWorkspaceOutline({...goodOutline, ok: undefined})).toThrow(/回执缺 ok/);
		expect(() => parseMapExplain({...goodExplain, ok: undefined})).toThrow(/回执缺 ok/);
	});
});

describe('客户端确实走了解析（不是转型完就 return）', () => {
	it('200 + 缺 truncated ⇒ 交给 codeMapStore 的 catch，而不是显示一张"完整"图', async () => {
		const {truncated: _drop, ...rest} = goodGraph;
		vi.stubGlobal('fetch', stubJson(rest));
		await expect(fetchWorkspaceGraph({root: 'D:/proj'})).rejects.toThrow(/fileCount \/ truncated/);
		vi.unstubAllGlobals();
	});

	it('200 + 缺 symbols ⇒ 抛给面板的 catch', async () => {
		const {symbols: _drop, ...rest} = goodOutline;
		vi.stubGlobal('fetch', stubJson(rest));
		await expect(fetchWorkspaceOutline('a.ts', 'D:/proj')).rejects.toThrow(/回执缺 symbols/);
		vi.unstubAllGlobals();
	});

	it('200 + 缺 summary ⇒ 抛而不是写「（无摘要）」', async () => {
		const {summary: _drop, ...rest} = goodExplain;
		vi.stubGlobal('fetch', stubJson(rest));
		await expect(explainMapNode('a.ts', 'file', 'D:/proj')).rejects.toThrow(/没有说明/);
		vi.unstubAllGlobals();
	});

	it('形状完整的三份回执仍按原样返回（不拦真实返回）', async () => {
		vi.stubGlobal('fetch', stubJson(goodGraph));
		await expect(fetchWorkspaceGraph({refresh: true, root: 'D:/proj'})).resolves.toMatchObject({fileCount: 2});
		vi.stubGlobal('fetch', stubJson(goodOutline));
		await expect(fetchWorkspaceOutline('a.ts', 'D:/proj')).resolves.toMatchObject({path: 'a.ts'});
		vi.stubGlobal('fetch', stubJson(goodExplain));
		await expect(explainMapNode('a.ts', 'file', 'D:/proj')).resolves.toMatchObject({kind: 'file'});
		vi.unstubAllGlobals();
	});
});
