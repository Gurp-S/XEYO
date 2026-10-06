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
import {readdirSync, readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {describe, expect, it} from 'vitest';

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** src/lib 下所有非测试 .ts，返回相对 src/lib 的路径（`api.ts`、`api/jobs.ts`…）。 */
function libFiles(dir = '..', prefix = ''): string[] {
	const out: string[] = [];
	for (const entry of readdirSync(path.join(HERE, dir), {withFileTypes: true})) {
		if (entry.isDirectory()) {
			out.push(...libFiles(path.join(dir, entry.name), `${prefix}${entry.name}/`));
			continue;
		}
		if (!entry.name.endsWith('.ts') || entry.name.endsWith('.test.ts')) {
			continue;
		}
		out.push(`${prefix}${entry.name}`);
	}
	return out.sort();
}
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
	// 钉在 api/workspaceReceipt.test.ts；git 4 处（status / log / branches / file diff）
	// 换成 parseGit*，钉在 api/gitReceipt.test.ts；terminal / session task 各 1 处
	// 换成 parseTerminalResult、parseSessionTask，钉在 api/terminalReceipt.test.ts
	// 与 api/sessionTaskReceipt.test.ts。剩 3 处：inbox 2（他人 lane）、rewindGc 1（rewind lane）。
	'api.ts': 3,
	'api/localModels.ts': 1,
	'api/memory.ts': 0, // 既有 memory 回执校验已消除裸转型，收紧棘轮。
	'api/usage.ts': 2,
	// 工作区地图正本（刻意放在 api/ 外，见该文件首注释）——之前根本不在棘轮的
	// 扫描名单里，等于这一族的裸转型对门禁完全隐身。3 处已换成 parse*，钉在
	// api/mapReceipt.test.ts；api.ts 里那份同名死副本一并删除。
	'workspaceMapApi.ts': 0,
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

	it('写侧同样全覆盖：未登记的 .ts 一旦冒出这类写法就红', () => {
		const unlisted = libFiles()
			.filter(f => !(f in WRITE_BASELINE))
			.filter(f => writeCountOf(f) > 0)
			.map(f => `${f}(${writeCountOf(f)})`);
		expect(unlisted).toEqual([]);
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

	// 扫描名单过去是手抄的：地图正本 lib/workspaceMapApi.ts 故意放在 api/ 目录外，
	// 于是它的三处裸转型对门禁完全隐身（棘轮"全绿"却根本没看它）。
	// 现在改成递归扫 src/lib 下所有 .ts：新增文件自动进入视野，不需要有人记得加。
	it('lib 下所有 .ts 都在棘轮视野内（含 api/ 外的正本）', () => {
		const files = libFiles();
		// 反空转哨兵：扫描本身必须真的跑起来，否则下面那条断言会绿成"没有违规"。
		expect(files).toContain('api.ts');
		expect(files).toContain('workspaceMapApi.ts');
		expect(files.length).toBeGreaterThan(20);
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
		// 14 → 10：git 4 处换成 parseGit*（api/gitReceipt.test.ts）。
		// 10 → 8：terminal 与 session task 各 1 处换成 parse*。
		// 8 → 7：地图正本 workspaceMapApi.ts 的 3 处换成 parse*（api/mapReceipt.test.ts），
		// 并删掉 api.ts 里那份没人 import 的同名死副本 fetchWorkspaceGraph。
		// 7 → 6：memory 已有校验，见本文件 api/memory.ts 的清零记录。
		expect(sum).toBe(6);
	});
});
