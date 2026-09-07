import { Box, Text } from "ink";
import React from "react";
import { theme } from "../theme.js";

type Props = { text: string };

export function SystemNote({ text }: Props) {
  const t = theme();
  return (
    <Box marginBottom={0} paddingLeft={0}>
      <Text color={t.muted} dimColor>
        {text}
      </Text>
    </Box>
  );
}
