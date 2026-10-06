#!/usr/bin/env node
import { render } from "ink";
import React from "react";
import { homedir } from "node:os";
import { resolve } from "node:path";
import { readFileSync, existsSync } from "node:fs";
import { App } from "./app/App.js";
import { argValue, missingOptionValues, positionalPrompt } from "./lib/cliArgs.js";
import { runJsonChat } from "./runJson.js";
import { detectColorMode, initTheme, type ColorMode } from "./theme.js";
import { TUI_RENDER_OPTIONS } from "./lib/renderOptions.js";
import type { CliConfig } from "./types.js";

function hasFlag(argv: string[], name: string): boolean {
  return argv.includes(name);
}

/**
 * T30：读后端端口文件（JSON {port, pid, ...}，兼容旧纯数字），不再钉死 :8000。
 * 查找顺序：XEYO_PORT_FILE > cwd 向上 3 级的 .xeyo/backend_port。
 */
function backendPortFromFile(): number | null {
  const readPort = (file: string): number | null => {
    try {
      const raw = readFileSync(file, "utf8").trim();
      if (!raw) return null;
      if (raw.startsWith("{")) {
        const data = JSON.parse(raw) as { port?: unknown };
        return typeof data.port === "number" && data.port > 0 ? data.port : null;
      }
      const n = Number(raw);
      return Number.isFinite(n) && n > 0 ? n : null;
    } catch {
      return null;
    }
  };
  const override = process.env.XEYO_PORT_FILE;
  if (override) return readPort(override);
  let dir = resolve(process.cwd());
  for (let i = 0; i < 3; i++) {
    const hit = readPort(resolve(dir, ".xeyo", "backend_port"));
    if (hit != null) return hit;
    const parent = resolve(dir, "..");
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function loadTomlHints(): Partial<CliConfig> {
  const home =
    process.env.XEYO_HOME ||
    process.env.XEYO_DATA_DIR ||
    resolve(homedir(), ".xeyo");
  const path = resolve(home, "config.toml");
  if (!existsSync(path)) return {};
  try {
    const text = readFileSync(path, "utf8");
    const get = (key: string) => {
      const m = text.match(new RegExp(`^${key}\\s*=\\s*"([^"]*)"`, "m"));
      return m?.[1];
    };
    return {
      apiKey: get("api_key") || "",
      provider: get("provider") || undefined,
      model: get("model") || undefined,
      baseUrl: get("server_base_url") || get("base_url") || undefined,
      cwd: get("last_cwd") || undefined,
      permissionMode: get("permission_mode") || undefined,
    };
  } catch {
    return {};
  }
}

function buildConfig(argv: string[]): CliConfig {
  const file = loadTomlHints();
  const demo = hasFlag(argv, "--demo");
  const cwd =
    argValue(argv, "--cwd") ||
    process.env.XEYO_CWD ||
    file.cwd ||
    process.cwd();
  return {
    baseUrl:
      argValue(argv, "--base-url") ||
      process.env.XEYO_SERVER_URL ||
      file.baseUrl ||
      // T30：跟随后端端口文件（后端迁移端口后仍可连）
      (backendPortFromFile() != null
        ? `http://127.0.0.1:${backendPortFromFile()}`
        : undefined) ||
      "http://127.0.0.1:8000",
    apiKey:
      argValue(argv, "--api-key") ||
      process.env.XEYO_MODEL_API_KEY ||
      process.env.DEEPSEEK_API_KEY ||
      file.apiKey ||
      "",
    provider:
      argValue(argv, "--provider") ||
      process.env.XEYO_MODEL ||
      file.provider ||
      "deepseek",
    model:
      argValue(argv, "--model") ||
      process.env.XEYO_MODEL_NAME ||
      file.model ||
      "",
    cwd: resolve(cwd),
    // T31：会话 id 由服务端签发；不在这里自造 UUID（仅 --session 显式指定）。
    sessionId: argValue(argv, "--session") || "",
    agentMode: argValue(argv, "--agent-mode") || "agent",
    permissionMode:
      argValue(argv, "--permission-mode") ||
      process.env.XEYO_PERMISSION_MODE ||
      file.permissionMode ||
      "risk",
    demo,
  };
}

function resolveColorMode(argv: string[]): ColorMode {
  const colorArg = argValue(argv, "--color")?.toLowerCase();
  const plain = hasFlag(argv, "--plain");
  const noColor =
    plain ||
    hasFlag(argv, "--no-color") ||
    colorArg === "never" ||
    (process.env.NO_COLOR != null && colorArg !== "always");

  if (noColor && colorArg !== "always") return "none";
  if (colorArg === "always" || process.env.FORCE_COLOR) {
    // 为 Ink 覆盖管道/NO_COLOR 环境；可用时仍优先 truecolor。
    const auto = detectColorMode({
      ...process.env,
      NO_COLOR: undefined,
    });
    return auto === "none" ? "ansi16" : auto;
  }
  return detectColorMode();
}

function printHelp(): void {
  console.log(`XEYO TUI (TypeScript / Ink)

  npm start                 interactive chat
  npm run demo              one-shot UI showcase
  npm start -- --cwd PATH
  npm start -- --json "hi"  machine-readable NDJSON (scripts / pipes)

Options:
  --demo --cwd --session --provider --model --api-key
  --base-url --permission-mode --agent-mode
  --json                    NDJSON events to stdout (no TUI)
  --ascii                   plain glyphs (no Unicode blocks)
  --no-color                disable ANSI colors (also honors NO_COLOR)
  --color=auto|always|never
  --plain                   ascii + no-color + reduced motion
  --reduced-motion          static spinners (also CI / non-TTY)

Engine: Python FastAPI (same as GUI)
  py -3.11 -m cli serve --cwd <project>

Config: ~/.xeyo/config.toml
`);
}

function restoreCursor(): void {
  try {
    if (process.stdin.isTTY) process.stdin.setRawMode?.(false);
  } catch {
    /* 忽略 */
  }
  try {
    process.stdout.write("\x1b[?25h");
  } catch {
    /* 忽略 —— 管道已断开 */
  }
}

const argv = process.argv.slice(2);
if (hasFlag(argv, "--help") || hasFlag(argv, "-h")) {
  printHelp();
  process.exit(0);
}

// 带值选项漏了值：必须报错退出。静默走默认值会让 --cwd --json hi 这类写法
// 既不进 JSON 模式、又把 "--json" 之外的目录当成工程（旧行为）。
const missingValues = missingOptionValues(argv);
if (missingValues.length > 0) {
  console.error(
    `缺少取值：${missingValues.join(", ")}（每个都需要紧跟一个值，或用 --名字=值 的写法）`,
  );
  process.exit(2);
}

const jsonMode =
  hasFlag(argv, "--json") || argValue(argv, "--format") === "json";
const plain = hasFlag(argv, "--plain");
const ascii =
  plain || hasFlag(argv, "--ascii") || process.env.XEYO_ASCII === "1";
const reduced =
  plain ||
  jsonMode ||
  hasFlag(argv, "--reduced-motion") ||
  process.env.XEYO_REDUCED_MOTION === "1";

initTheme({
  mode: plain ? "none" : resolveColorMode(argv),
  ascii: ascii || plain,
  reducedMotion: reduced,
});

const config = buildConfig(argv);
const prompt = positionalPrompt(argv);

// 质量门：管道 / 非 TTY 时走 JSON，或拒绝启动 Ink（避免 Broken Pipe 崩溃）。
const interactiveOk = Boolean(process.stdout.isTTY && process.stdin.isTTY);

if (jsonMode) {
  const code = await runJsonChat(config, prompt);
  process.exit(code);
}

if (!interactiveOk) {
  console.error(
    "XEYO TUI needs a terminal. Use --json \"prompt\" for scripts/pipes, or run in an interactive TTY.",
  );
  process.exit(2);
}

// 传 TUI_RENDER_OPTIONS 关掉 ink 内建 Ctrl+C 退出（否则忙时 Ctrl+C 直接退
// 全屏、routeKey 的 interrupt 永远收不到按键，见 lib/renderOptions.ts）。
const instance = render(<App config={config} />, TUI_RENDER_OPTIONS);

const shutdown = () => {
  try {
    instance.unmount();
  } catch {
    /* 忽略 */
  }
  restoreCursor();
};

process.on("SIGINT", () => {
  shutdown();
  process.exit(130);
});
process.on("SIGTERM", () => {
  shutdown();
  process.exit(143);
});
process.on("uncaughtException", (err) => {
  restoreCursor();
  console.error(err);
  process.exit(1);
});
process.on("unhandledRejection", (err) => {
  restoreCursor();
  console.error(err);
  process.exit(1);
});
process.on("exit", restoreCursor);
