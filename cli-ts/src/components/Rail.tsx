import { Box } from "ink";
import React, { type ReactNode } from "react";
import { border } from "../theme.js";

type Props = {
  children: ReactNode;
  /** 来自 theme() 的语义化边框颜色。 */
  color?: string;
  marginBottom?: number;
  paddingLeft?: number;
};

/**
 * 仅左侧竖轨 —— 做次级分组，不用完整方框。
 * 准则：完整边框只留给焦点 / 弹窗。
 */
export function Rail({
  children,
  color,
  marginBottom = 1,
  paddingLeft = 1,
}: Props) {
  return (
    <Box
      flexDirection="column"
      borderStyle={border.rail}
      borderColor={color}
      borderTop={false}
      borderBottom={false}
      borderRight={false}
      borderLeft
      paddingLeft={paddingLeft}
      marginBottom={marginBottom}
    >
      {children}
    </Box>
  );
}
