import { Box, Text } from "ink";
import React from "react";
import { theme } from "../theme.js";

type Props = {
  text: string;
  streaming?: boolean;
  usage?: string;
  /** 模型思考增量（reasoning_delta 累加），只显示最后 200 字符。 */
  reasoning?: string;
};

/**
 * Claude-like assistant: bare prose, no speaker chrome.
 */
export function AssistantBlock({ text, streaming, usage, reasoning }: Props) {
  const t = theme();

  if (!text && streaming) {
    return (
      <Box marginBottom={1}>
        <Text color={t.muted} dimColor>
          …
        </Text>
      </Box>
    );
  }

  if (!text) return null;

  const reasoningTail =
    reasoning && reasoning.length > 200 ? reasoning.slice(-200) : reasoning;

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text>{text}</Text>
      {reasoningTail ? (
        <Text color={t.muted} dimColor>
          思考 · {reasoningTail}
        </Text>
      ) : null}
      {usage && !streaming ? (
        <Text color={t.muted} dimColor>
          {usage}
        </Text>
      ) : null}
    </Box>
  );
}
