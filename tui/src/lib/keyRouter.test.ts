/**
 * 键盘路由真值表。重点钉住"授权弹窗把终端锁死"这一类：控制键必须永远优先于
 * 弹窗，否则等授权的那一轮既不能取消、过期弹窗也关不掉。
 */
import assert from "node:assert/strict";
import test from "node:test";

import { routeKey, type KeyContext } from "./keyRouter.js";

const IDLE: KeyContext = { busy: false, pending: false, showHelp: false, hasError: false };
const WAITING: KeyContext = { busy: true, pending: true, showHelp: false, hasError: false };
const STALE: KeyContext = { busy: false, pending: true, showHelp: false, hasError: false };

test("控制键优先于弹窗：等授权时仍能取消", () => {
  assert.equal(routeKey("c", { ctrl: true }, WAITING), "interrupt");
  assert.equal(routeKey("C", { ctrl: true }, WAITING), "interrupt");
  assert.equal(routeKey("", { escape: true }, WAITING), "interrupt");
});

test("过期弹窗（流已结束却没有决议）有关掉的路", () => {
  assert.equal(routeKey("", { escape: true }, STALE), "dismiss_pending");
  assert.equal(routeKey("c", { ctrl: true }, STALE), "dismiss_pending");
});

test("空闲时 ctrl-c 退出；弹窗挡不住它", () => {
  assert.equal(routeKey("c", { ctrl: true }, IDLE), "exit");
});

test("弹窗在场时字母键决议，其余键不外泄给输入框", () => {
  for (const k of ["a", "A", "y", "Y"]) assert.equal(routeKey(k, {}, STALE), "allow");
  for (const k of ["d", "D", "n", "N"]) assert.equal(routeKey(k, {}, STALE), "deny");
  assert.equal(routeKey("r", {}, STALE), "remind");
  assert.equal(routeKey("x", {}, STALE), "pass_to_input");
});

test("esc 在没有弹窗也没有在跑时只收面板", () => {
  assert.equal(routeKey("", { escape: true }, { ...IDLE, showHelp: true }), "clear_panels");
  assert.equal(routeKey("", { escape: true }, { ...IDLE, hasError: true }), "clear_panels");
  assert.equal(routeKey("", { escape: true }, IDLE), "pass_to_input");
});

test("历史与补全只在空闲且无弹窗时生效", () => {
  assert.equal(routeKey("", { upArrow: true }, IDLE), "history_older");
  assert.equal(routeKey("", { downArrow: true }, IDLE), "history_newer");
  assert.equal(routeKey("", { tab: true }, IDLE), "tab_complete");
  assert.equal(routeKey("", { upArrow: true }, { ...IDLE, busy: true }), "pass_to_input");
  assert.equal(routeKey("", { upArrow: true }, STALE), "pass_to_input");
  assert.equal(routeKey("", { tab: true }, WAITING), "pass_to_input");
});
