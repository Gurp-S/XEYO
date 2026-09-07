/**
 * 统一斜杠命令 —— CLI-TS 面的解析（补全在 PromptLine.tsx）。
 * 命令表来自生成物 `../generated/slashManifest.js`（单一事实源：
 * python/slash/registry.py，改表后跑 `py -3.11 -m slash.export_manifest`）。
 */
import { type SlashCommand, slashCommands } from "../generated/slashManifest.js";

const SURFACES = new Set(["tui"]);

export type SlashParseResult = {
  isSlash: boolean;
  /** 命中 manifest 的命令；未知 /xxx 时为 undefined */
  command?: SlashCommand;
  /** 规范命令名（含未知时的首 token） */
  name: string;
  arg: string;
  /** / 开头但不在 tui 可用面 */
  unknown: boolean;
};

export function parseSlashInput(text: string): SlashParseResult {
  const raw = (text ?? "").trim();
  if (!raw.startsWith("/")) {
    return { isSlash: false, name: "", arg: "", unknown: false };
  }
  const body = raw.slice(1).trim();
  if (!body) return { isSlash: true, name: "", arg: "", unknown: false };
  const head = body.split(/\s+/, 1)[0] ?? "";
  const rest = body.slice(head.length).trim();
  const lower = head.toLowerCase();
  const command = slashCommands.find(
    (c) =>
      (c.name === lower || c.aliases.some((a) => a.toLowerCase() === lower)) &&
      c.surfaces.some((s) => SURFACES.has(s)),
  );
  if (!command) {
    return { isSlash: true, name: head, arg: rest, unknown: true };
  }
  return { isSlash: true, command, name: command.name, arg: rest, unknown: false };
}

export function formatSlashHelp(): string {
  const lines: string[] = [
    "tui 是薄客户端：会话列表 / /load 恢复 / 审批在本地（经服务端）；其余命令由服务端引擎执行（〔服务端〕）",
  ];
  for (const c of slashCommands) {
    if (!c.surfaces.some((s) => SURFACES.has(s))) continue;
    const alias = c.aliases.length
      ? `（${c.aliases.slice(0, 3).join("/")}）`
      : "";
    const where = c.handler === "server" ? "〔服务端〕" : "〔本地〕";
    lines.push(`${c.usage}  ${c.summary}${alias} ${where}`);
  }
  return lines.join("\n");
}
