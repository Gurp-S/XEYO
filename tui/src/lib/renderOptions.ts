/**
 * ink 的 exitOnCtrlC 默认 true：Ctrl+C 先被 ink 拦下（App.handleInput 在
 * useInput 订阅者之前同步卸载整棵树，use-input 还会显式跳过 ctrl+c），永远
 * 到不了 lib/keyRouter 的 "interrupt" 分支——忙时按 Ctrl+C 会直接退出 TUI、
 * 且不 POST /v1/interrupt（服务端回合没人停）。关掉内建退出，把 Ctrl+C 完整
 * 交给 routeKey 分流：忙=停回合、弹窗=关弹窗、空闲=退出。
 */
export const TUI_RENDER_OPTIONS = { exitOnCtrlC: false } as const;
