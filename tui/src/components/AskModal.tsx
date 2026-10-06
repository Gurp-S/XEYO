import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import React from "react";
import type { AskPrompt } from "../lib/askPrompt.js";
import { border, g, theme } from "../theme.js";

type Props = {
  prompt: AskPrompt;
  /** 自由文本模式的草稿值与提交句柄（选项模式不渲染输入框）。 */
  draft: string;
  onDraftChange: (v: string) => void;
  onSubmitText: (value: string) => void;
};

/**
 * 提问作答弹窗（#10）：与 PermissionModal 同款单框形制。
 * - 有选项：数字 1..n 直接提交该项；`s` 显式跳过（空答案）；esc 关闭。
 * - 无选项：自由文本输入（光标在此，PromptLine 输入已让位）；Enter 提交。
 * - 多题向导：本端只提示改用桌面端（逐题向导属后续项），不假装能答。
 */
export function AskModal({ prompt, draft, onDraftChange, onSubmitText }: Props) {
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
        {gly.warn} 需要你的回答
      </Text>
      <Box marginTop={0}>
        <Text bold>{prompt.question || "(无题面)"}</Text>
      </Box>
      {prompt.extraQuestions > 0 ? (
        <Text color={t.muted}>
          多题向导（{prompt.extraQuestions + 1} 题）：请在桌面端作答；Esc 关闭本弹窗。
        </Text>
      ) : prompt.options.length > 0 ? (
        <Box marginTop={1} flexDirection="column">
          {prompt.options.map((opt, i) => (
            <Text key={`${i}-${opt}`}>
              <Text color={t.accent} bold>
                {i + 1}
              </Text>
              <Text color={t.soft}> {opt}</Text>
            </Text>
          ))}
          <Box marginTop={1} flexDirection="column">
            <Text color={t.muted}>数字 = 选择并提交 · s = 跳过（空答案）</Text>
            <Text color={t.muted}>esc 关闭（模型将等待答复或超时）</Text>
          </Box>
        </Box>
      ) : (
        <Box marginTop={1} flexDirection="column">
          <Box>
            <Text color={t.accent}>{gly.prompt} </Text>
            <TextInput
              value={draft}
              onChange={onDraftChange}
              onSubmit={onSubmitText}
              placeholder="输入回答后回车"
            />
          </Box>
          <Text color={t.muted}>enter 提交 · esc 关闭（模型将等待答复或超时）</Text>
        </Box>
      )}
    </Box>
  );
}
