import { Box, Text } from "ink";
import React from "react";
import { clipSmart, g, theme } from "../theme.js";
import type { ToolStatus } from "../types.js";

/** 已结束工具的折叠态 —— 单行安静展示（紧凑 transcript 风格）。 */
export function ToolLine({
  name,
  summary,
  status,
  isError,
}: {
  name: string;
  summary: string;
  status: ToolStatus;
  isError?: boolean;
}) {
  const t = theme();
  const gly = g();
  const failed = status === "error" || isError;
  return (
    <Box marginBottom={0}>
      <Text color={failed ? t.error : t.muted}>
        {failed ? gly.fail : gly.bullet}{" "}
      </Text>
      <Text color={t.muted}>{name}</Text>
      {summary ? (
        <Text color={t.muted} dimColor>
          {" "}
          {clipSmart(summary, 52)}
        </Text>
      ) : null}
    </Box>
  );
}
