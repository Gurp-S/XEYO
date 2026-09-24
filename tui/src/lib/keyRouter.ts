/**
 * 键盘事件的归属判定：把「谁处理这次按键」从组件里抽出来，好让取消授权弹窗
 * 这条路径有真值表可测（终端没 TTY 时无法用交互验证）。
 */
export type KeyAction =
  | "interrupt"
  | "dismiss_pending"
  | "allow"
  | "remind"
  | "deny"
  | "clear_panels"
  | "exit"
  | "history_older"
  | "history_newer"
  | "tab_complete"
  | "pass_to_input";

export type KeyFlags = {
  ctrl?: boolean;
  escape?: boolean;
  upArrow?: boolean;
  downArrow?: boolean;
  tab?: boolean;
};

export type KeyContext = {
  busy: boolean;
  pending: boolean;
  showHelp: boolean;
  hasError: boolean;
};

/**
 * 控制键永远先于授权弹窗：等授权的那一轮必须能取消；弹窗过期（流已结束却没
 * 收到 permission_resolved）时也得有出路——否则任意按键都被弹窗吃掉，终端锁死。
 */
export function routeKey(input: string, key: KeyFlags, ctx: KeyContext): KeyAction {
  if (key.ctrl && input.toLowerCase() === "c") {
    if (ctx.busy) return "interrupt";
    if (ctx.pending) return "dismiss_pending";
    return "exit";
  }
  if (key.escape) {
    if (ctx.busy) return "interrupt";
    if (ctx.pending) return "dismiss_pending";
    if (ctx.showHelp || ctx.hasError) return "clear_panels";
    return "pass_to_input";
  }
  if (ctx.pending) {
    const c = input.toLowerCase();
    if (c === "a" || c === "y") return "allow";
    if (c === "r") return "remind";
    if (c === "d" || c === "n") return "deny";
    return "pass_to_input";
  }
  if (!ctx.busy) {
    if (key.upArrow) return "history_older";
    if (key.downArrow) return "history_newer";
    if (key.tab) return "tab_complete";
  }
  return "pass_to_input";
}
