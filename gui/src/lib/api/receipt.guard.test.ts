/// <reference types="node" />
/**
 * receipt.guard.test.ts — HTTP 回执"裸转型"的棘轮守卫。
 *
 * 反复出现的一类缺陷（本轮就修了 4 处：runtimePreset 读侧、runtimeMode 写侧、
 * uploads 两个函数）：客户端把 200 的响应体 `as` 成目标类型直接返回，
 * 于是一个缺字段/空串/形状变了的回执会被当成"确认过了"，
 * 界面再把它读成"没有"或"已生效"。
 *
 * 存量太多（26 处），一次性改完会把无关模块全卷进这次提交，
 * 所以这里做**棘轮**：把每个文件当前的裸转型数量钉死。
 * 新增裸转型 ⇒ 红；把某处修成校验型 ⇒ 同步调小这里的数字（这是好事，写明即可）。
 *
 * 只认"转型后立刻 return"这一种形状（正则见 CAST_RETURN），
 * 因为它是零校验的最直白写法；先取回 payload 再检查若干字段后返回的写法不算。
 */
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {describe, expect, it} from 'vitest';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CAST_RETURN = /return\s+\(?await\s+(?:res|response|r)\.json\(\)\)?\s+as\s/g;
/**
 * 第二类：写侧只认 HTTP 状态。`return res.ok;` 把"200 + {ok:false}"、
 * "200 但回执缺字段"、"200 空体"全当成保存成功。后端已经为这一类改过路由
 * （rewind-gc 的 docstring 点名"GUI 只看 res.ok ⇒ keep_recent=0 被拒渲染成保存成功"），
 * 但同类写法一开始有 14 处，现已逐处换成带回执的写法（见下方基线的清零记录）。
 */
const WRITE_STATUS_ONLY = /^\s*return res\.ok;$/gm;

/** 存量基线：文件 → 裸转型处数。修一处就调小一处。 */
const BASELINE: Record<string, number> = {
	// 工作区读写那 5 处（listing / search / read / stat / write 回显）已换成
	// parseWorkspace*（200 但形状不对就抛，走各 store 已有的 catch 分支），
	// 钉在 api/workspaceReceipt.test.ts。剩 10 处按 lane 分组：
	// inbox 2、sessionTask 1、workspaceGraph 1、git 4、terminal 1、rewindGc 1。
	'api.ts': 10,
	'api/localModels.ts': 1,
	'api/memory.ts': 1,
	'api/usage.ts': 2,
};

/** 写侧"只认 HTTP 状态"的存量基线。 */
const WRITE_BASELINE: Record<string, number> = {
	'api.ts': 12,
	'api/usage.ts': 1,
};
// api/diagnostics.ts 的那一处（deleteDiagPin 的 `return res.ok;`）已改成读 body 的
// {ok,error}，并钉在 diagnostics.write.test.ts 里 —— 棘轮按设计把这一格清零。

function textOf(rel: string): string {
	return readFileSync(path.join(HERE, '..', rel), 'utf8').replace(/\r\n/g, '\n');
}

function countOf(rel: string): number {
	return (textOf(rel).match(CAST_RETURN) ?? []).length;
}

function writeCountOf(rel: string): number {
	return (textOf(rel).match(WRITE_STATUS_ONLY) ?? []).length;
}

describe('写侧只认 HTTP 状态的棘轮', () => {
	it('基线里的每个文件都还在，且这类写法没有增长', () => {
		const drift: string[] = [];
		for (const [rel, want] of Object.entries(WRITE_BASELINE)) {
			const got = writeCountOf(rel);
			if (got !== want) {
				drift.push(`${rel}: 基线 ${want} 处，实测 ${got} 处`);
			}
		}
		expect(drift).toEqual([]);
	});

	it('哨兵：这类写法抓得住，带回执的写法不该被抓', () => {
		const bad = '\t\ttry {\n\t\t\tconst res = await fetch(u);\n\t\t\treturn res.ok;\n\t\t} catch {\n\t\t\treturn false;\n\t\t}';
		expect((bad.match(WRITE_STATUS_ONLY) ?? []).length).toBe(1);
		const good = '\t\tconst body = await res.json();\n\t\treturn {ok: body.ok === true, message: ""};';
		expect((good.match(WRITE_STATUS_ONLY) ?? []).length).toBe(0);
	});
});

describe('HTTP 回执裸转型棘轮', () => {
	it('基线里的每个文件都还在，且裸转型数没有增长', () => {
		const drift: string[] = [];
		for (const [rel, want] of Object.entries(BASELINE)) {
			const got = countOf(rel);
			if (got !== want) {
				drift.push(`${rel}: 基线 ${want} 处，实测 ${got} 处`);
			}
		}
		expect(drift).toEqual([]);
	});

	it('新出现的裸转型文件必须先进基线（防止静默扩张）', () => {
		const files = [
			'api.ts',
			...[
				'localModels.ts',
				'memory.ts',
				'usage.ts',
				'permissions.ts',
				'jobs.ts',
				'references.ts',
				'skills.ts',
				'mcp.ts',
				'plugins.ts',
				'goals.ts',
				'chatStream.ts',
				'diagnostics.ts',
				'uploads.ts',
				'runtimeMode.ts',
				'runtimePreset.ts',
				'core.ts',
			].map(f => `api/${f}`),
		];
		const unlisted = files
			.filter(f => !(f in BASELINE))
			.filter(f => countOf(f) > 0)
			.map(f => `${f}(${countOf(f)})`);
		expect(unlisted).toEqual([]);
	});

	// 哨兵：正则本身必须还在匹配那种写法。哪天 transform/格式化工具把源码
	// 改成多行形态而正则失配，两条断言会同时"绿"成零违规——这条就是它的探针。
	it('哨兵：正则确实抓得住被禁的写法', () => {
		const sample = [
			'async function f() {',
			'\tconst res = await fetch(u);',
			'\treturn (await res.json()) as {ok: boolean};',
			'}',
		].join('\n');
		expect((sample.match(CAST_RETURN) ?? []).length).toBe(1);
		// 反向哨兵：校验过的写法不该被抓。
		const okSample =
			'\tconst body = (await res.json()) as T;\n\tif (body.ok !== true) throw new Error("x");\n\treturn body;';
		expect((okSample.match(CAST_RETURN) ?? []).length).toBe(0);
	});

	it('基线总量与逐文件之和一致（防漏记）', () => {
		const sum = Object.values(BASELINE).reduce((a, b) => a + b, 0);
		// 19 → 14：工作区读写 5 处换成 parseWorkspace*（api/workspaceReceipt.test.ts）。
		expect(sum).toBe(14);
	});
});
