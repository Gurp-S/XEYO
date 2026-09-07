import { Box, Text } from "ink";
import React from "react";
import { g, theme } from "../theme.js";

type Props = { text: string };

/**
 * 用户输入回显：❯ 前缀，无边框 / 无说话人标签。
 */
export function UserBubble({ text }: Props) {
  const t = theme();
  const gly = g();
  const lines = text.split("\n");
  return (
    <Box flexDirection="column" marginBottom={1} marginTop={1}>
      {lines.map((line, i) => (
        <Box key={i}>
          <Text color={t.accent} bold>
            {i === 0 ? `${gly.prompt} ` : "  "}
          </Text>
          <Text>{line || " "}</Text>
        </Box>
      ))}
    </Box>
  );
}
