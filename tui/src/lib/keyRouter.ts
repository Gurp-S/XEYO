/**
 * 键盘事件的归属判定：把「谁处理这次按键」从组件里抽出来，好让取消授权弹窗
 * 这条路径有真值表可测（终端没 TTY 时无法用交互验证）。
 */
export type KeyAction =
  | "interrupt"
  | "dismiss_pending"
  | "dismiss_ask"
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
  /** 提问作答弹窗在场（#10）：Esc=关闭；选项数字键由 App 层分流。 */
  askPending?: boolean;
  showHelp: boolean;
  hasError: boolean;
  /** 弹窗是多会话冲突三选（服务端给了 choices）——只有这一档有"提醒"键。 */
  peerChoice?: boolean;
};

/**
 * 控制键与弹窗的归属判定。基准：等授权的那一轮必须能取消；弹窗过期（流已结束
 * 却没收到 permission_resolved）时也得有出路——否则任意按键都被弹窗吃掉，终端锁死。
 *
 * 2026-10-06（#15）：Esc 在**弹窗在场**时与 GUI 对齐——Esc=拒绝该请求（会话继续），
 * 「停整回合」留给无弹窗态（Ctrl+C 与无弹窗 Esc 承担）；同手势跨表面不再两义。
 */
export function routeKey(input: string, key: KeyFlags, ctx: KeyContext): KeyAction {
  if (key.ctrl && input.toLowerCase() === "c") {
    if (ctx.busy) return "interrupt";
    if (ctx.pending) return "dismiss_pending";
    return "exit";
  }
  if (key.escape) {
    if (ctx.pending) return ctx.busy ? "deny" : "dismiss_pending";
    if (ctx.askPending) return "dismiss_ask";
    if (ctx.busy) return "interrupt";
    if (ctx.showHelp || ctx.hasError) return "clear_panels";
    return "pass_to_input";
  }
  if (ctx.pending) {
    const c = input.toLowerCase();
    if (c === "a" || c === "y") return "allow";
    // 提醒 = 不执行 + 双方下轮提醒，只存在于三选弹窗；普通确认按 r 不发决议，
    // 否则会把一次"允许/拒绝"的意图改道成 deny + peer 冲突记录。
    if (c === "r") return ctx.peerChoice ? "remind" : "pass_to_input";
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
