/**
 * receipt.guard.test.ts — TUI 侧 HTTP 回执"裸转型"的棘轮守卫（对齐 gui 的同名门）。
 *
 * 这一族在本项目反复出现：客户端只查 HTTP 状态，把 200 的响应体 `as` 成目标类型直接返回，
 * 于是缺字段的回执被当成"确认过的值"，界面再把它读成"没有"或"成功"。
 * TUI 的四个会话 helper 刚刚才补齐（见 sse.ts 的 parse*），这里把它们钉住：
 * **新增一处就红**，除非先改成带回执/带形状校验的写法。
 *
 * 只认两种最直白的写法（正则见 CAST_RETURN / WRITE_STATUS_ONLY），
 * 先取回 payload 再逐字段检查的形态不算违规 —— 那正是 parse* 的样子。
 */
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CAST_RETURN = /return\s+\(?await\s+(?:res|response|r)\.json\(\)\)?\s+as\s/g;
const WRITE_STATUS_ONLY = /^\s*return res\.ok;$/gm;

/** 读侧裸转型的存量基线：修一处就调小，新增一处必须红。 */
const CAST_BASELINE: Record<string, number> = {
  "api/sse.ts": 0,
};

/**
 * 写侧"只认 HTTP 状态"的存量。`api/sse.ts` 的那一处是 healthOk：
 * /health 的 200 本身就是结论（没有信封），所以它不是同一族缺陷 ——
 * 但必须显式登记在这里，否则下一个 `return res.ok;` 混进来没人拦。
 */
const WRITE_BASELINE: Record<string, number> = {
  "api/sse.ts": 1,
};

function sourceFiles(dir = "..", prefix = ""): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(path.join(HERE, dir), { withFileTypes: true })) {
    if (entry.isDirectory()) {
      out.push(...sourceFiles(path.join(dir, entry.name), `${prefix}${entry.name}/`));
      continue;
    }
    if (!/\.(ts|tsx)$/.test(entry.name) || entry.name.includes(".test.")) continue;
    out.push(`${prefix}${entry.name}`);
  }
  return out.sort();
}

function textOf(rel: string): string {
  return readFileSync(path.join(HERE, "..", rel), "utf8").replace(/\r\n/g, "\n");
}

function countOf(rel: string, rx: RegExp): number {
  return (textOf(rel).match(rx) ?? []).length;
}

test("扫描确实跑起来了（反空转哨兵）", () => {
  const files = sourceFiles();
  assert.ok(files.includes("api/sse.ts"), `没扫到 api/sse.ts：${files.slice(0, 5)}`);
  assert.ok(files.length > 10, `src 下只扫出 ${files.length} 个文件，口径一定变了`);
  const sample =
    "\tconst res = await fetch(u);\n\treturn (await res.json()) as {ok: boolean};";
  assert.equal((sample.match(CAST_RETURN) ?? []).length, 1);
  const okSample =
    "\tconst body = await res.json();\n\tif (body.ok !== true) throw new Error('x');\n\treturn body;";
  assert.equal((okSample.match(CAST_RETURN) ?? []).length, 0);
  assert.equal((("\treturn res.ok;\n").match(WRITE_STATUS_ONLY) ?? []).length, 1);
});

test("读侧裸转型没有增长", () => {
  const drift: string[] = [];
  for (const [rel, want] of Object.entries(CAST_BASELINE)) {
    const got = countOf(rel, CAST_RETURN);
    if (got !== want) drift.push(`${rel}: 基线 ${want} 处，实测 ${got} 处`);
  }
  // 未登记的文件一旦出现这种写法也要红。
  for (const rel of sourceFiles()) {
    if (rel in CAST_BASELINE) continue;
    const got = countOf(rel, CAST_RETURN);
    if (got > 0) drift.push(`${rel}: 未登记的裸转型 ${got} 处`);
  }
  assert.deepEqual(drift, []);
});

test("写侧只认 HTTP 状态的存量没有增长", () => {
  const drift: string[] = [];
  for (const [rel, want] of Object.entries(WRITE_BASELINE)) {
    const got = countOf(rel, WRITE_STATUS_ONLY);
    if (got !== want) drift.push(`${rel}: 基线 ${want} 处，实测 ${got} 处`);
  }
  for (const rel of sourceFiles()) {
    if (rel in WRITE_BASELINE) continue;
    const got = countOf(rel, WRITE_STATUS_ONLY);
    if (got > 0) drift.push(`${rel}: 未登记的"只看状态码"写法 ${got} 处`);
  }
  assert.deepEqual(drift, []);
});
