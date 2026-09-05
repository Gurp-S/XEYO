/**
 * XEYO 视觉系统 —— 紧凑的终端密度 + XEYO 青色品牌标识。
 * 层级：位置 → 间距 → 字重 → 最后才是颜色。
 * 边框即标点：仅焦点/弹窗使用完整方框。
 */

export const space = {
  0: 0,
  1: 1,
  2: 2,
  4: 4,
} as const;

/** 共享边框语言：圆角 = 焦点/弹窗；单线轨 = 少见的次级样式。 */
export const border = {
  style: "round" as const,
  rail: "single" as const,
};

export type ColorMode = "truecolor" | "ansi16" | "none";

export type Theme = {
  accent: string | undefined;
  accentSoft: string | undefined;
  success: string | undefined;
  warning: string | undefined;
  error: string | undefined;
  text: string | undefined;
  soft: string | undefined;
  muted: string | undefined;
  border: string | undefined;
  borderFocus: string | undefined;
  borderSuccess: string | undefined;
  borderWarning: string | undefined;
  borderError: string | undefined;
};

const TRUECOLOR: Theme = {
  accent: "#2DD4BF",
  accentSoft: "#14B8A6",
  success: "#4ADE80",
  warning: "#FBBF24",
  error: "#F87171",
  text: "#E5E7EB",
  soft: "#A1A1AA",
  muted: "#71717A",
  border: "#3F3F46",
  borderFocus: "#2DD4BF",
  borderSuccess: "#22C55E",
  borderWarning: "#D97706",
  borderError: "#EF4444",
};

/** 具名 ANSI 色 —— 相比硬编码 RGB 在亮/暗终端下表现更稳定。 */
const ANSI16: Theme = {
  accent: "cyan",
  accentSoft: "cyan",
  success: "green",
  warning: "yellow",
  error: "red",
  text: undefined,
  soft: "gray",
  muted: "gray",
  border: "gray",
  borderFocus: "cyan",
  borderSuccess: "green",
  borderWarning: "yellow",
  borderError: "red",
};

const PLAIN: Theme = {
  accent: undefined,
  accentSoft: undefined,
  success: undefined,
  warning: undefined,
  error: undefined,
  text: undefined,
  soft: undefined,
  muted: undefined,
  border: undefined,
  borderFocus: undefined,
  borderSuccess: undefined,
  borderWarning: undefined,
  borderError: undefined,
};

/**
 * 符号语言（XEYO 保留 Ӿ 标记）。
 * ⏺ 工具 · ⎿ 结果 · ❯ 提示符 · ✓/✗ 状态
 */
export const glyphs = {
  mark: "Ӿ",
  prompt: "❯",
  bullet: "⏺",
  result: "⎿",
  branch: "⎿",
  ok: "✓",
  fail: "✗",
  warn: "⚠",
  live: "●",
  idle: "○",
} as const;

export const glyphsAscii = {
  mark: "X",
  prompt: ">",
  bullet: "*",
  result: ">",
  branch: "\\",
  ok: "+",
  fail: "x",
  warn: "!",
  live: "*",
  idle: "o",
} as const;

export type GlyphSet = {
  mark: string;
  prompt: string;
  bullet: string;
  result: string;
  branch: string;
  ok: string;
  fail: string;
  warn: string;
  live: string;
  idle: string;
};

let _mode: ColorMode = "truecolor";
let _ascii = false;
let _reducedMotion = false;
let _theme: Theme = TRUECOLOR;
let _glyphs: GlyphSet = glyphs;

export function detectColorMode(env: NodeJS.ProcessEnv = process.env): ColorMode {
  if (
    env.NO_COLOR != null ||
    env.XEYO_NO_COLOR === "1" ||
    env.TERM === "dumb" ||
    !process.stdout.isTTY
  ) {
    return "none";
  }
  if (env.COLORTERM === "truecolor" || env.COLORTERM === "24bit") {
    return "truecolor";
  }
  if (process.platform === "win32" && env.WT_SESSION) return "truecolor";
  return "ansi16";
}

export function detectReducedMotion(env: NodeJS.ProcessEnv = process.env): boolean {
  return (
    env.XEYO_REDUCED_MOTION === "1" ||
    env.CI === "true" ||
    env.CI === "1" ||
    !process.stdout.isTTY
  );
}

export function initTheme(opts?: {
  mode?: ColorMode;
  ascii?: boolean;
  reducedMotion?: boolean;
}): Theme {
  _mode = opts?.mode ?? detectColorMode();
  _ascii = Boolean(opts?.ascii || process.env.XEYO_ASCII === "1");
  _reducedMotion = Boolean(
    opts?.reducedMotion ?? detectReducedMotion(),
  );
  _glyphs = _ascii ? glyphsAscii : glyphs;
  _theme =
    _mode === "none" ? PLAIN : _mode === "ansi16" ? ANSI16 : TRUECOLOR;
  return _theme;
}

export function theme(): Theme {
  return _theme;
}

export function g(): GlyphSet {
  return _glyphs;
}

export function colorMode(): ColorMode {
  return _mode;
}

export function isAscii(): boolean {
  return _ascii;
}

export function reducedMotion(): boolean {
  return _reducedMotion;
}

function cellWidth(ch: string): number {
  return /[\u1100-\u115F\u2E80-\uA4CF\uAC00-\uD7A3\uF900-\uFAFF\uFE10-\uFE6F\uFF00-\uFF60]/.test(
    ch,
  )
    ? 2
    : 1;
}

function measure(s: string): number {
  let w = 0;
  for (const ch of s) w += cellWidth(ch);
  return w;
}

/** 按近似显示宽度截断（CJK 字符 ≈ 2 列 —— 尽力估算）。 */
export function clipCells(s: string, max: number): string {
  const t = s.replace(/\s+/g, " ").trim();
  let w = 0;
  let out = "";
  for (const ch of t) {
    const cw = cellWidth(ch);
    if (w + cw > max) return `${out}…`;
    out += ch;
    w += cw;
  }
  return out;
}

/**
 * 路径感知截断：保留开头 + 结尾（扩展名 / 文件名）。
 */
export function clipPath(s: string, max: number): string {
  const t = s.replace(/\\/g, "/").trim();
  if (measure(t) <= max) return t;
  if (max < 8) return clipCells(t, max);
  const parts = t.split("/").filter(Boolean);
  const leaf = parts[parts.length - 1] || t;
  const leafKeep = Math.min(measure(leaf), Math.max(6, Math.floor(max * 0.55)));
  const leafClip = clipCells(leaf, leafKeep);
  const budget = max - measure(leafClip) - 1;
  if (budget < 4) return `…${leafClip}`;
  let head = "";
  for (const p of parts.slice(0, -1)) {
    const next = head ? `${head}/${p}` : p;
    if (measure(next) > budget) break;
    head = next;
  }
  if (!head) {
    const headBudget = Math.max(3, budget - 1);
    return `${clipCells(t, headBudget)}…${leafClip}`;
  }
  return `${head}/…/${leafClip}`;
}

export function clipSmart(s: string, max: number): string {
  const t = s.trim();
  if (/[/\\]/.test(t) || /\.[a-zA-Z0-9]{1,8}$/.test(t)) {
    return clipPath(t, max);
  }
  return clipCells(t, max);
}
