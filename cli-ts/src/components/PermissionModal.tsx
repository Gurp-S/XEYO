import { Box, Text } from "ink";
import React from "react";
import { border, g, theme } from "../theme.js";
import type { PermissionPrompt } from "../types.js";

type Props = {
  pending: PermissionPrompt;
};

/** 聚焦的权限确认面板 —— 单个方框，按键显式列出。 */
export function PermissionModal({ pending }: Props) {
  const t = theme();
  const gly = g();
  return (
    <Box
      flexDirection="column"
      borderStyle={border.style}
      borderColor={t.borderWarning}
      paddingX={1}
      marginY={1}
    >
      <Text color={t.warning} bold>
        {gly.warn} Allow tool?
      </Text>
      <Box marginTop={0}>
        <Text bold>{pending.tool}</Text>
      </Box>
      {pending.prompt ? (
        <Text color={t.soft}>{pending.prompt}</Text>
      ) : null}
      <Box marginTop={1} flexDirection="column">
        <Text>
          <Text color={t.success} bold>
            a
          </Text>
          <Text color={t.muted}> allow</Text>
        </Text>
        <Text>
          <Text color={t.error} bold>
            d
          </Text>
          <Text color={t.muted}> deny</Text>
        </Text>
        <Text>
          <Text color={t.warning} bold>
            r
          </Text>
          <Text color={t.muted}> allow + remind</Text>
        </Text>
      </Box>
    </Box>
  );
}
