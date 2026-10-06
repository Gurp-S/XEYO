import assert from "node:assert/strict";
import test from "node:test";

import {
  askKeyIntent,
  askReceipt,
  parseAskPending,
} from "./askPrompt.js";

test("ask_user_pending 帧解析：选项兼容字符串与 {label}", () => {
  const p = parseAskPending({
    request_id: "req_1",
    question: "选哪个？",
    options: ["甲", {label: "乙"}, ""],
    default: "甲",
    questions: [{}, {}],
  });
  assert.ok(p);
  assert.deepEqual(p!.options, ["甲", "乙"]);
  assert.equal(p!.defaultAnswer, "甲");
  assert.equal(p!.extraQuestions, 1);
});

test("缺 request_id 的帧解析为 null（开不了可决议的弹窗）", () => {
  assert.equal(parseAskPending({question: "x"}), null);
  assert.equal(parseAskPending({request_id: "  "}), null);
});

test("选项态单键意图：数字提交该项、s 显式跳过、其余 none", () => {
  const options = ["甲", "乙"];
  assert.deepEqual(askKeyIntent("1", {options}), {kind: "submit", value: "甲"});
  assert.deepEqual(askKeyIntent("2", {options}), {kind: "submit", value: "乙"});
  assert.deepEqual(askKeyIntent("9", {options}), {kind: "none"});
  assert.deepEqual(askKeyIntent("0", {options}), {kind: "none"});
  assert.deepEqual(askKeyIntent("s", {options}), {kind: "submit", value: ""});
  assert.deepEqual(askKeyIntent("S", {options}), {kind: "submit", value: ""});
  assert.deepEqual(askKeyIntent("a", {options}), {kind: "none"});
});

test("作答回执：空答案显式出声（与静默空提交不是一回事）", () => {
  assert.match(askReceipt(""), /空答案/);
  assert.match(askReceipt("  "), /空答案/);
  assert.match(askReceipt("甲"), /已提交作答/);
});
