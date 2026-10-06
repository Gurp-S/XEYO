import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { createElement } from "react";
import { render } from "ink";
import { App } from "./App.js";
import { TUI_RENDER_OPTIONS } from "../lib/renderOptions.js";
import type { CliConfig } from "../types.js";

/**
 * 离线假 TTY：ink 从 stdin 的 'readable' 事件循环 read() 取块；
 * stdout 只累计写入（并给 ink 拿列宽/行数）。
 */
function fakeTty() {
  const stdinEe = new EventEmitter();
  const queue: string[] = [];
  const stdin = Object.assign(stdinEe, {
    isTTY: true,
    setRawMode: () => {},
    setEncoding: () => {},
    resume: () => {},
    ref: () => {},
    unref: () => {},
    read: () => (queue.shift() ?? null) as string | null,
  });
  let output = "";
  const stdout = Object.assign(new EventEmitter(), {
    isTTY: true,
    columns: 100,
    rows: 40,
    write: (s: string) => {
      output += s;
      return true;
    },
  });
  return {
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    send: (chunk: string) => {
      queue.push(chunk);
      stdinEe.emit("readable");
    },
    output: () => output,
  };
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

const CONFIG: CliConfig = {
  baseUrl: "http://127.0.0.1:9",
  apiKey: "",
  provider: "deepseek",
  model: "",
  cwd: process.cwd(),
  sessionId: "",
  agentMode: "agent",
  permissionMode: "risk",
  demo: true,
};

// Ctrl+C 的归属是 routeKey 契约（忙=停回合 + POST /v1/interrupt，空闲/弹窗各
// 有分流）。ink 的 exitOnCtrlC 默认 true 时有两层拦截：App.handleInput 在
// useInput 订阅者之前同步卸载整棵树；use-input 还显式跳过 ctrl+c。⇒ 该按键
// 永远到不了 routeKey（红相实测=整个 TUI 直接退，时间线无中断标记）。接线锁：
// 渲染必须带 TUI_RENDER_OPTIONS（lib/renderOptions）。
const OPTIONS = TUI_RENDER_OPTIONS;

test("忙时 Ctrl+C：走 interrupt（不退出、时间线出现中断标记）", async () => {
  const tty = fakeTty();
  const instance = render(createElement(App, { config: CONFIG }), {
    stdin: tty.stdin,
    stdout: tty.stdout,
    patchConsole: false,
    ...OPTIONS,
  });
  // ink 的 exitPromise 懒创建：必须在卸载发生之前调用，否则永远不结算。
  const exited = instance.waitUntilExit().then(() => "exited" as const);
  try {
    await sleep(600); // demo 回合进行中（busy=true）
    tty.send("\x03");
    const outcome = await Promise.race([
      exited,
      sleep(500).then(() => "alive" as const),
    ]);
    assert.equal(
      outcome,
      "alive",
      "Ctrl+C 把整个 TUI 退掉了（ink exitOnCtrlC 没被关）",
    );
    assert.match(tty.output(), /interrupted/, "时间线没有出现中断标记");
  } finally {
    instance.unmount();
  }
});
