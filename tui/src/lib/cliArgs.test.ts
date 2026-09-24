/**
 * CLI 参数解析的回归（node --test + tsx）。
 *
 * 两条都是实测出来的旧行为，根因是"带值选项的清单被抄了两遍且已经不一致"：
 * - `--cwd --json hi` 旧实现把 `--json` 当成 cwd 的值：既没进 JSON 模式，
 *   又把一个不存在的目录当工程。
 * - `--format json hi` 的跳过清单里没有 `--format`，于是提示词变成 `json hi`。
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  argValue,
  isOptionLike,
  missingOptionValues,
  positionalPrompt,
} from "./cliArgs.js";

test("取到值 / = 形式 / 显式空串", () => {
  assert.equal(argValue(["--cwd", "/x"], "--cwd"), "/x");
  assert.equal(argValue(["--color=mono"], "--color"), "mono");
  // `--name=` 是用户显式给的空值，不能和"没写"混为一谈。
  assert.equal(argValue(["--api-key="], "--api-key"), "");
  assert.equal(argValue(["--model"], "--model"), undefined);
  assert.equal(argValue(["--provider", "deepseek"], "--model"), undefined);
});

test("绝不把后面的选项吞成取值", () => {
  assert.equal(argValue(["--cwd", "--json", "hi"], "--cwd"), undefined);
  assert.equal(argValue(["--session", "--plain"], "--session"), undefined);
});

test("漏值能被入口查出来", () => {
  assert.deepEqual(missingOptionValues(["--cwd"]), ["--cwd"]);
  assert.deepEqual(missingOptionValues(["--cwd", "--json"]), ["--cwd"]);
  assert.deepEqual(missingOptionValues(["--cwd", "/x"]), []);
  assert.deepEqual(missingOptionValues(["--format=json"]), []);
  assert.deepEqual(missingOptionValues([]), []);
});

test("--format 的取值不再漏进自由文本提示词", () => {
  assert.equal(positionalPrompt(["--format", "json", "hi"]), "hi");
  assert.equal(positionalPrompt(["--cwd", "/x", "描述任务"]), "描述任务");
  assert.equal(positionalPrompt(["--json", "描述任务"]), "描述任务");
});

test("-- 之后的内容原样作为提示词，哪怕长得像选项", () => {
  assert.equal(positionalPrompt(["--", "--json", "raw text"]), "--json raw text");
});

test("提示词里可以带空格，末尾空白被裁掉", () => {
  assert.equal(positionalPrompt(["修一下 这个 bug  "]), "修一下 这个 bug");
});

test("isOptionLike 不把单个连字符 / 负数当选项", () => {
  assert.equal(isOptionLike("--cwd"), true);
  assert.equal(isOptionLike("-m"), true);
  assert.equal(isOptionLike("-"), false);
  assert.equal(isOptionLike(""), false);
});
