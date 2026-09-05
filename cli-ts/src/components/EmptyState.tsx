import { Box, Text } from "ink";
import React from "react";
import { g, theme } from "../theme.js";

type Props = {
  connected: boolean | null;
};

/** Quiet empty — Claude leaves the canvas almost blank. */
export function EmptyState({ connected }: Props) {
  const t = theme();
  const gly = g();
  return (
    <Box flexDirection="column" marginY={1} paddingLeft={0}>
      <Text color={t.muted} dimColor>
        {gly.prompt} Ask XEYO to do something
      </Text>
      {connected === false ? (
        <Text color={t.warning}>
          {gly.warn} Offline —{" "}
          <Text color={t.accent} bold>
            py -3.11 -m cli serve
          </Text>
        </Text>
      ) : (
        <Text color={t.muted} dimColor>
          /help · /demo · ?
        </Text>
      )}
    </Box>
  );
}
