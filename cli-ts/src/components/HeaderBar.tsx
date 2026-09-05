import { Box, Text } from "ink";
import React from "react";
import { LOGO_GLYPH } from "../logo.js";
import { clipPath, g, isAscii, theme } from "../theme.js";
import type { CliConfig } from "../types.js";
import { formatElapsed } from "../hooks/useElapsed.js";
import { Spinner } from "./Spinner.js";

type Props = {
  config: CliConfig;
  connected: boolean | null;
  busy: boolean;
  turnCount: number;
  elapsedSec?: number;
};

/**
 * Claude-like status strip — one quiet line, no rule bar.
 * Only elevates color when offline or non-agent mode.
 */
export function HeaderBar({
  config,
  connected,
  busy,
  turnCount,
  elapsedSec = 0,
}: Props) {
  const t = theme();
  const gly = g();
  const mark = isAscii() ? gly.mark : LOGO_GLYPH;
  const cwd = clipPath(
    config.cwd.replace(/\\/g, "/").split("/").pop() || config.cwd,
    18,
  );

  return (
    <Box marginBottom={1} justifyContent="space-between">
      <Box>
        <Text color={t.accent} bold>
          {mark}
        </Text>
        <Text color={t.muted} dimColor>
          {" "}
          {cwd}
        </Text>
        {config.agentMode !== "agent" ? (
          <Text color={t.warning}> · {config.agentMode}</Text>
        ) : null}
      </Box>
      <Box>
        {busy ? (
          <>
            <Spinner ascii={isAscii()} label="thinking" />
            {elapsedSec > 0 ? (
              <Text color={t.muted} dimColor>
                {" "}
                {formatElapsed(elapsedSec)}
              </Text>
            ) : null}
          </>
        ) : turnCount > 0 ? (
          <Text color={t.muted} dimColor>
            {turnCount} turn{turnCount === 1 ? "" : "s"}
          </Text>
        ) : null}
        {connected === false ? (
          <>
            <Text color={t.muted} dimColor>
              {busy || turnCount > 0 ? " · " : ""}
            </Text>
            <Text color={t.warning}>{gly.idle} offline</Text>
          </>
        ) : null}
      </Box>
    </Box>
  );
}
