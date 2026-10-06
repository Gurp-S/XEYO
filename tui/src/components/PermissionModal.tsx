import { Box, Text } from "ink";
import React from "react";
import { isPeerChoicePrompt } from "../lib/permissionPrompt.js";
import { border, g, theme } from "../theme.js";
import type { PermissionPrompt } from "../types.js";

type Props = {
  pending: PermissionPrompt;
};

/** 聚焦的权限确认面板 —— 单个方框，按键显式列出。 */
export function PermissionModal({ pending }: Props) {
  const t = theme();
  const gly = g();
  const peer = isPeerChoicePrompt(pending);
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
        {/* 「提醒」= 不执行 + 双方下轮各挂提醒（多会话冲突三选）；普通确认没有这一档。 */}
        {peer ? (
          <Text>
            <Text color={t.warning} bold>
              r
            </Text>
            <Text color={t.muted}> remind（不执行 · 双方下轮提醒）</Text>
          </Text>
        ) : null}
        <Text color={t.muted}>
          esc / ctrl-c 取消等待（本轮已结束时只关闭弹窗）
        </Text>
      </Box>
    </Box>
  );
}
