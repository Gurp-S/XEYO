import { Box, Text } from "ink";
import React from "react";
import { clipSmart, g, theme } from "../theme.js";
import type { ToolStatus } from "../types.js";

/** Collapsed settled tool — one quiet line (Claude transcript density). */
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
