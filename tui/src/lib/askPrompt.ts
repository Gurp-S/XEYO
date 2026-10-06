/**
 * TUI 提问（AskUserQuestion）作答面的纯逻辑：帧解析与单键意图判定。
 * App 接线在无 TTY 下不可交互，判定与解析在真值表里钉住（房内惯例）。
 */

export type AskPrompt = {
  requestId: string;
  question: string;
  options: string[];
  defaultAnswer: string | null;
  /** 向导剩余题数（questions.length - 1）；>0 时本端只提示用桌面端（见 App）。 */
  extraQuestions: number;
};

/** 解析 `ask_user_pending` 帧；缺 request_id 时返回 null（开不了可决议的弹窗）。 */
export function parseAskPending(xy: Record<string, unknown>): AskPrompt | null {
  const requestId = String(xy.request_id ?? "").trim();
  if (!requestId) return null;
  const options = Array.isArray(xy.options)
    ? xy.options
        .map((o) =>
          typeof o === "string"
            ? o
            : String((o as { label?: unknown } | null)?.label ?? ""),
        )
        .filter((s) => s.length > 0)
    : [];
  const rawDefault = xy.default;
  const questions = Array.isArray(xy.questions) ? xy.questions.length : 0;
  return {
    requestId,
    question: String(xy.question ?? "").trim(),
    options,
    defaultAnswer:
      typeof rawDefault === "string" && rawDefault.trim() ? rawDefault : null,
    extraQuestions: questions > 1 ? questions - 1 : 0,
  };
}

export type AskKeyIntent = {kind: "submit"; value: string} | {kind: "none"};

/**
 * 选项态的单键意图：数字=n 提交第 n 项；`s`=显式跳过（提交空答案，出声）；
 * 其余 none（由弹窗外的全局键继续处理）。
 */
export function askKeyIntent(
  key: string,
  prompt: Pick<AskPrompt, "options">,
): AskKeyIntent {
  if (/^[1-9]$/.test(key)) {
    const opt = prompt.options[Number(key) - 1];
    if (opt !== undefined) return {kind: "submit", value: opt};
  }
  if (key.toLowerCase() === "s") return {kind: "submit", value: ""};
  return {kind: "none"};
}

/** 作答回执文案（空答案必须显式出声——与 CLI 静默空提交不是一件事）。 */
export function askReceipt(answer: string): string {
  return answer.trim() === "" ? "已提交空答案（显式跳过）" : "已提交作答";
}
