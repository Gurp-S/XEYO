import { Box, Text } from "ink";
import React from "react";
import { slashCommands } from "../generated/slashManifest.js";
import { border, theme } from "../theme.js";

const TUI_SURFACES = new Set(["tui"]);

/** 命令行来自生成 manifest（tui 面），快捷键保留固定行。 */
const COMMAND_ROWS: { cmd: string; tip: string }[] = slashCommands
  .filter((c) => c.surfaces.some((s) => TUI_SURFACES.has(s)))
  .map((c) => ({
    cmd: c.usage,
    tip: c.aliases.length
      ? `${c.summary}（${c.aliases.slice(0, 3).join("/")}）`
      : c.summary,
  }));

const ROWS: { cmd: string; tip: string }[] = [
  ...COMMAND_ROWS,
  { cmd: "Tab", tip: "Cycle slash completions" },
  { cmd: "↑ / ↓", tip: "Input history" },
  { cmd: "Esc", tip: "Interrupt · dismiss" },
  { cmd: "Ctrl+C", tip: "Interrupt · or quit if idle" },
];

/** 快捷键面板 —— 弹窗样式（使用完整边框）。 */
export function HelpPanel() {
  const t = theme();
  return (
    <Box
      flexDirection="column"
      borderStyle={border.style}
      borderColor={t.border}
      paddingX={1}
      marginBottom={1}
    >
      <Text color={t.accent} bold>
        Shortcuts
      </Text>
      <Box marginTop={1} flexDirection="column">
        {ROWS.map((r) => (
          <Box key={r.cmd}>
            <Box width={26}>
              <Text color={t.soft}>{r.cmd}</Text>
            </Box>
            <Text color={t.muted} dimColor>
              {r.tip}
            </Text>
          </Box>
        ))}
      </Box>
      <Box marginTop={1}>
        <Text color={t.muted} dimColor>
          Esc to close
        </Text>
      </Box>
    </Box>
  );
}
