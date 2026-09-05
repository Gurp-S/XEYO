import { Box, Text } from "ink";
import React from "react";
import { g, theme } from "../theme.js";

type Props = {
  cols: number;
  rows?: number;
};

const MIN_COLS = 48;

/** Skill: tiny fallback — keep quit / recovery visible. */
export function TinyFallback({ cols }: Props) {
  const t = theme();
  const gly = g();
  if (cols >= MIN_COLS) return null;
  return (
    <Box flexDirection="column" marginBottom={1} paddingX={1}>
      <Text color={t.warning}>
        {gly.warn} Terminal is {cols} cols — prefer ≥{MIN_COLS}
      </Text>
      <Text color={t.muted} dimColor>
        Try --plain · /exit to quit
      </Text>
    </Box>
  );
}

export const TINY_MIN_COLS = MIN_COLS;
