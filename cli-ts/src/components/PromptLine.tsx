import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import React, { useMemo } from "react";
import { formatElapsed } from "../hooks/useElapsed.js";
import { slashCommands } from "../generated/slashManifest.js";
import { border, g, isAscii, theme } from "../theme.js";
import { Spinner } from "./Spinner.js";

/** CLI-TS 可用面（gui / remote 命令不进补全）。 */
const CLI_TS_SURFACES = new Set(["cli_ts"]);

const visible = slashCommands.filter((c) =>
  c.surfaces.some((s) => CLI_TS_SURFACES.has(s)),
);

export const SLASH_COMMANDS = visible.map((c) => `/${c.name}`) as string[];

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  mode: string;
  busy: boolean;
  hint?: string;
  connected?: boolean | null;
  elapsedSec?: number;
  suggestIndex?: number;
};

/** 由生成 manifest 驱动的补全：前缀匹配规范名与别名。 */
export function slashMatches(value: string): string[] {
  if (!value.startsWith("/") || value.includes(" ")) return [];
  const p = value.slice(1).toLowerCase();
  if (!p) return SLASH_COMMANDS;
  const out: string[] = [];
  for (const c of visible) {
    if (c.name.startsWith(p)) out.push(`/${c.name}`);
    else if (c.aliases.some((a) => a.toLowerCase().startsWith(p))) {
      out.push(`/${c.name}`);
    }
  }
  return [...new Set(out)];
}

/**
 * 聚焦提示行：圆角方框 + ❯ 提示符。
 * 提示信息位于方框外（无嵌套装饰）。
 */
export function PromptLine({
  value,
  onChange,
  onSubmit,
  mode,
  busy,
  hint,
  connected,
  elapsedSec = 0,
  suggestIndex = 0,
}: Props) {
  const t = theme();
  const gly = g();

  const suggestions = useMemo(() => slashMatches(value), [value]);
  const hi = suggestions.length
    ? ((suggestIndex % suggestions.length) + suggestions.length) %
      suggestions.length
    : 0;

  const defaultHint =
    connected === false
      ? "engine offline · py -3.11 -m cli serve · or /demo"
      : busy
        ? `esc to interrupt${elapsedSec > 0 ? ` · ${formatElapsed(elapsedSec)}` : ""}`
        : "? for shortcuts · ↑↓ history · tab";

  return (
    <Box flexDirection="column" marginTop={1}>
      <Box
        borderStyle={border.style}
        borderColor={busy ? t.borderFocus : t.border}
        paddingX={1}
      >
        <Text color={t.accent} bold>
          {gly.prompt}{" "}
        </Text>
        {mode !== "agent" ? (
          <Text color={t.warning}>{mode} </Text>
        ) : null}
        {busy ? (
          <Spinner
            ascii={isAscii()}
            label={
              elapsedSec > 0
                ? `working ${formatElapsed(elapsedSec)}`
                : "working…"
            }
          />
        ) : (
          <TextInput
            value={value}
            onChange={onChange}
            onSubmit={onSubmit}
            placeholder=""
          />
        )}
      </Box>

      {suggestions.length > 0 ? (
        <Box marginLeft={1} flexDirection="column">
          {suggestions.map((s, i) => (
            <Text
              key={s}
              color={i === hi ? t.accent : t.muted}
              bold={i === hi}
              dimColor={i !== hi}
            >
              {i === hi ? `${gly.prompt} ` : "  "}
              {s}
            </Text>
          ))}
        </Box>
      ) : (
        <Box marginLeft={1}>
          <Text color={t.muted} dimColor>
            {hint ?? defaultHint}
          </Text>
        </Box>
      )}
    </Box>
  );
}
