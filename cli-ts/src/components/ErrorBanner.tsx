import { Box, Text } from "ink";
import React from "react";
import { border, g, theme } from "../theme.js";

export function ErrorBanner({ message }: { message: string }) {
  const t = theme();
  const gly = g();
  return (
    <Box
      flexDirection="column"
      borderStyle={border.style}
      borderColor={t.borderError}
      paddingX={1}
      marginBottom={1}
    >
      <Text color={t.error} bold>
        {gly.fail} Error
      </Text>
      <Text>{message}</Text>
      <Box marginTop={1} flexDirection="column">
        <Text color={t.muted} dimColor>
          esc dismiss
        </Text>
        <Text color={t.muted} dimColor>
          Next:{" "}
          <Text color={t.accent}>py -3.11 -m cli serve</Text>
          {" · "}
          <Text color={t.accent}>/demo</Text>
          {" · "}
          <Text color={t.accent}>--json "…"</Text>
        </Text>
      </Box>
    </Box>
  );
}
