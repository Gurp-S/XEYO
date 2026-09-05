import { Box, Text } from "ink";
import React from "react";
import { isAscii, theme } from "../theme.js";
import { AssistantBlock } from "./AssistantBlock.js";
import { SystemNote } from "./SystemNote.js";
import { ToolCard } from "./ToolCard.js";
import { ToolLine } from "./ToolLine.js";
import { TurnDivider } from "./TurnDivider.js";
import { UserBubble } from "./UserBubble.js";
import type { TimelineItem, TodoRow, TodoStatus, UsageInfo } from "../types.js";

type Props = {
  item: TimelineItem;
  /** 将已结束的工具折叠为单行。 */
  compactTools?: boolean;
  turnIndex?: number;
  showTurnDivider?: boolean;
};

export function TimelineItemView({
  item,
  compactTools,
  turnIndex,
  showTurnDivider,
}: Props) {
  return (
    <Box flexDirection="column">
      {showTurnDivider && turnIndex != null ? (
        <TurnDivider index={turnIndex} />
      ) : null}
      {item.kind === "user" ? <UserBubble text={item.text} /> : null}
      {item.kind === "assistant" ? (
        <AssistantBlock
          text={item.text}
          streaming={item.streaming}
          usage={usageLine(item.usage)}
          reasoning={item.reasoning}
        />
      ) : null}
      {item.kind === "tool" ? (
        <>
          {compactTools && item.status !== "running" ? (
            <ToolLine
              name={item.name}
              summary={item.summary}
              status={item.status}
              isError={item.isError}
            />
          ) : (
            <ToolCard
              name={item.name}
              summary={item.summary}
              status={item.status}
              result={item.result}
              isError={item.isError}
              progress={item.progress}
            />
          )}
          {item.todos && item.todos.length > 0 ? (
            <TodoRows todos={item.todos} />
          ) : null}
        </>
      ) : null}
      {item.kind === "system" ? <SystemNote text={item.text} /> : null}
    </Box>
  );
}

/** 把结构化 usage 渲染成单行：“token 消耗: {prompt}+{completion} · ¥{cny}”。 */
function usageLine(u: UsageInfo | undefined): string | undefined {
  if (!u) return undefined;
  const base = `token 消耗: ${u.promptTokens}+${u.completionTokens}`;
  return u.cny != null ? `${base} · ¥${fmtCny(u.cny)}` : base;
}

function fmtCny(v: number): string {
  if (v === 0) return "0";
  return v.toFixed(4).replace(/\.?0+$/, "");
}

function todoMark(status: TodoStatus, ascii: boolean): string {
  if (status === "completed") return ascii ? "x" : "●";
  if (status === "in_progress") return ascii ? "o" : "◐";
  return ascii ? "-" : "○";
}

function TodoRows({ todos }: { todos: TodoRow[] }) {
  const t = theme();
  const ascii = isAscii();
  return (
    <Box flexDirection="column" paddingLeft={2}>
      {todos.map((todo, i) => {
        const done = todo.status === "completed";
        const active = todo.status === "in_progress";
        return (
          <Box key={i}>
            <Text color={done ? t.success : active ? t.accent : t.muted}>
              {todoMark(todo.status, ascii)}
            </Text>
            <Text color={done ? t.muted : t.text} dimColor={done}>
              {" "}
              {todo.content}
            </Text>
          </Box>
        );
      })}
    </Box>
  );
}

/** 为用户消息编号轮次，供分隔符使用。 */
export function withTurnMeta(items: TimelineItem[]): {
  item: TimelineItem;
  turnIndex?: number;
  showTurnDivider: boolean;
}[] {
  let turn = 0;
  return items.map((item) => {
    if (item.kind === "user") {
      turn += 1;
      return {
        item,
        turnIndex: turn,
        showTurnDivider: turn > 1,
      };
    }
    return { item, showTurnDivider: false };
  });
}
