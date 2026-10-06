/**
 * 忙时提交的纯判定与回执文案（App 接线无 TTY 不可测，判定与文案在真值表里钉住）。
 *
 * 口径对齐：服务端 `_busy_or_queue`（queue_if_busy → 202 accepted_payload）与
 * GUI `resolveSendMode`（Enter=排队 / 加速键=边界引导，Codex queue vs TurnSteer 同形）。
 */
export type BusySubmitPlan = {
  queueIfBusy: true;
  steerIfBusy: boolean;
};

/** modifier=true（Ctrl/Cmd+Enter）= 边界引导（steered）；否则 = 回合结束后排队（queued）。 */
export function resolveBusySubmit(modifier: boolean): BusySubmitPlan {
  return {queueIfBusy: true, steerIfBusy: Boolean(modifier)};
}

/** 202 受理体的用户可见回执句（中性事实；含位次/口径，不承诺"已送达下一轮"以外的事）。 */
export function acceptedNote(payload: {
  queued?: boolean;
  steered?: boolean;
  delivery?: string;
  position?: number;
  queue_id?: string;
}): string {
  if (payload.steered === true) {
    return "已引导本轮：下一次采样前投递（不打断当前工具批次）";
  }
  const pos =
    typeof payload.position === "number" ? `（位次 ${payload.position}）` : "";
  return `上一轮进行中，消息已排队${pos}；回合结束后自动投递`;
}

/** 忙时打斜杠命令的拒绝文案（与 GUI `runSlashCommand` 的 idle 门同口径）。 */
export function busySlashNote(name: string): string {
  return `会话仍在运行，/${name} 暂不可执行；可用 /stop 或 Esc 中断当前回合。`;
}
