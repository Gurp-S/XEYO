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

/** Low-frequency spinner; static glyph when reduced motion / CI. */
export function Spinner({ label, ascii, color }: Props) {
  const [i, setI] = useState(0);
  const frames = ascii ? ASCII : FRAMES;
  const t = theme();
  const quiet = reducedMotion();

  useEffect(() => {
    if (quiet) return;
    // Skill: spinner ~150ms for short unknown waits (calm, not flashy).
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
