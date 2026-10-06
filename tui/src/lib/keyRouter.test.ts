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
/** 多会话冲突三选弹窗（服务端给了 choices）——只有这一档才有"提醒"。 */
const PEER: KeyContext = { ...STALE, peerChoice: true };

test("弹窗在场时 Esc=拒绝该请求（会话继续）；Ctrl+C 仍停回合（双出口）", () => {
  // 2026-10-06：#15——GUI 的 Esc 语义是「拒掉这条请求、回合继续」；TUI 此前
  // 把 Esc 借给「停整回合」，导致同一手势三表面两种含义。现在弹窗在场时
  // Esc 与 GUI 对齐（deny）；「停回合」留给无弹窗态（由 Ctrl+C 与无弹窗 Esc 承担）。
  assert.equal(routeKey("", { escape: true }, WAITING), "deny");
  assert.equal(routeKey("c", { ctrl: true }, WAITING), "interrupt");
  assert.equal(routeKey("C", { ctrl: true }, WAITING), "interrupt");
});

test("无弹窗在跑时 Esc 仍是停回合", () => {
  assert.equal(
    routeKey("", { escape: true }, { ...WAITING, pending: false }),
    "interrupt",
  );
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
  // 「提醒」只属于三选（多会话冲突）弹窗：普通请求没有这个动作，
  // 按 r 不许把一次继续/拦截的意图改道成"不执行 + peer 提醒"。
  assert.equal(routeKey("r", {}, STALE), "pass_to_input");
  assert.equal(routeKey("r", {}, PEER), "remind");
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

test("提问弹窗在场：Esc=关闭（dismiss_ask），不误停回合", () => {
  const ASK: KeyContext = {
    busy: true,
    pending: false,
    askPending: true,
    showHelp: false,
    hasError: false,
  };
  assert.equal(routeKey("", { escape: true }, ASK), "dismiss_ask");
  // 权限弹窗优先级高于提问弹窗（两种弹窗理论上不并存，但真碰上时先答权限）。
  assert.equal(
    routeKey("", { escape: true }, { ...ASK, pending: true }),
    "deny",
  );
});

test("无弹窗时 askPending 不改变原语义", () => {
  assert.equal(
    routeKey("", { escape: true }, { ...IDLE, askPending: false }),
    "pass_to_input",
  );
});
