import { Box } from "ink";
import React from "react";

/** 仅做柔和的节奏间隔 —— 无“第 N 轮”装饰。 */
export function TurnDivider(_props: { index: number }) {
  return <Box marginTop={1} />;
}
