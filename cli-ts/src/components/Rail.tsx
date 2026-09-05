import { Box } from "ink";
import React, { type ReactNode } from "react";
import { border } from "../theme.js";

type Props = {
  children: ReactNode;
  /** Semantic border color from theme(). */
  color?: string;
  marginBottom?: number;
  paddingLeft?: number;
};

/**
 * Left-only rail — secondary grouping without a full box.
 * Skill: reserve full borders for focus / modals.
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
