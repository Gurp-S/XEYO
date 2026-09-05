#!/usr/bin/env node
import { render } from "ink";
import React from "react";
import { homedir } from "node:os";
import { resolve } from "node:path";
import { readFileSync, existsSync } from "node:fs";
import { App } from "./app/App.js";
import { runJsonChat } from "./runJson.js";
import { detectColorMode, initTheme, type ColorMode } from "./theme.js";
import type { CliConfig } from "./types.js";

function argValue(argv: string[], name: string): string | undefined {
  const i = argv.indexOf(name);
  if (i >= 0 && argv[i + 1]) return argv[i + 1];
  const pref = `${name}=`;
  const hit = argv.find((a) => a.startsWith(pref));
  return hit ? hit.slice(pref.length) : undefined;
}

function hasFlag(argv: string[], name: string): boolean {
  return argv.includes(name);
}

/** Collect trailing freeform prompt (after flags). */
function positionalPrompt(argv: string[]): string {
  const out: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "--") {
      out.push(...argv.slice(i + 1));
      break;
    }
    if (a.startsWith("-")) {
      // skip flag values for known options that take args
      const takes =
        a === "--cwd" ||
        a === "--session" ||
        a === "--provider" ||
        a === "--model" ||
        a === "-m" ||
        a === "--api-key" ||
        a === "--base-url" ||
        a === "--permission-mode" ||
        a === "--agent-mode" ||
        a === "--color" ||
        a.startsWith("--color=");
      if (takes && !a.includes("=") && argv[i + 1] && !argv[i + 1]!.startsWith("-")) {
        i += 1;
      }
      continue;
    }
    out.push(a);
  }
  return out.join(" ").trim();
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
    // Override pipe/NO_COLOR for Ink; still prefer truecolor when available.
    const auto = detectColorMode({
      ...process.env,
      NO_COLOR: undefined,
    });
    return auto === "none" ? "ansi16" : auto;
  }
  return detectColorMode();
}

function printHelp(): void {
  console.log(`XEYO CLI (TypeScript / Ink)

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
    /* ignore */
  }
  try {
    process.stdout.write("\x1b[?25h");
  } catch {
    /* ignore — broken pipe */
  }
}

const argv = process.argv.slice(2);
if (hasFlag(argv, "--help") || hasFlag(argv, "-h")) {
  printHelp();
  process.exit(0);
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

// Quality gate: pipes / non-TTY → JSON or refuse Ink (Broken Pipe Panic).
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

const instance = render(<App config={config} />);

const shutdown = () => {
  try {
    instance.unmount();
  } catch {
    /* ignore */
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
