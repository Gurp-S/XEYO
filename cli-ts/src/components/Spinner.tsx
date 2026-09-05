import { Text } from "ink";
import React, { useEffect, useState } from "react";
import { reducedMotion, theme } from "../theme.js";

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const ASCII = ["|", "/", "-", "\\"];

type Props = {
  label?: string;
  ascii?: boolean;
  color?: string;
};

/** 低频 spinner；减弱动效 / CI 环境下显示静态符号。 */
export function Spinner({ label, ascii, color }: Props) {
  const [i, setI] = useState(0);
  const frames = ascii ? ASCII : FRAMES;
  const t = theme();
  const quiet = reducedMotion();

  useEffect(() => {
    if (quiet) return;
    // 准则：短时未知等待用约 150ms 的 spinner（安静不花哨）。
    const id = setInterval(() => setI((n) => (n + 1) % frames.length), 150);
    return () => clearInterval(id);
  }, [frames.length, quiet]);

  const glyph = quiet ? (ascii ? "*" : "●") : frames[i];

  return (
    <Text color={color ?? t.accent}>
      {glyph}
      {label ? ` ${label}` : ""}
    </Text>
  );
}
