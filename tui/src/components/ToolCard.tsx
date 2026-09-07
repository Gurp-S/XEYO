import { Box, Text } from "ink";
import React from "react";
import { clipSmart, g, isAscii, theme } from "../theme.js";
import type { ToolStatus } from "../types.js";
import { Spinner } from "./Spinner.js";

type Props = {
  name: string;
  summary: string;
  status: ToolStatus;
  result?: string;
  isError?: boolean;
  /** tool_progress 实时进度文案。 */
  progress?: string;
};

/**
 * 工具行卡片：
 *   ⏺ Read(path)
 *     ⎿ 结果片段
 */
export function ToolCard({ name, summary, status, result, isError, progress }: Props) {
  const t = theme();
  const gly = g();
  const failed = status === "error" || isError;
  const running = status === "running";
  const arg = summary ? `(${clipSmart(summary, 56)})` : "";

  return (
    <Box flexDirection="column" marginBottom={0} paddingLeft={0}>
      <Box>
        {running ? (
          <Spinner ascii={isAscii()} color={t.accent} />
        ) : (
          <Text color={failed ? t.error : t.accent}>
            {failed ? gly.fail : gly.bullet}
          </Text>
        )}
        <Text> </Text>
        <Text color={failed ? t.error : t.text} bold={!failed}>
          {name}
        </Text>
        {arg ? <Text color={t.muted}>{arg}</Text> : null}
      </Box>
      {running && progress ? (
        <Box paddingLeft={2}>
          <Text color={t.muted} dimColor>
            {gly.result} {clipSmart(progress, 72)}
          </Text>
        </Box>
      ) : null}
      {result ? (
        <Box paddingLeft={2}>
          <Text color={t.muted}>
            {gly.result} {clipSmart(result.replace(/\n/g, " "), 88)}
          </Text>
        </Box>
      ) : null}
    </Box>
  );
}
