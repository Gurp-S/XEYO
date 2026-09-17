"""A3 日快照「本次该写哪几天」的规划（纯函数，零 IO）。

背景（结构性根因）：A3 报告里出现的天 = 存在 ``deploy_project_mode_<day>`` 行的天；
该行唯一的写入入口是 ``memory_stack_eval --monitor-daily``。旧版 ``auto`` 取
「ledger 里最新的一天」，于是"覆盖哪天"由**运行时刻**决定、"报告有几行"由**运行次数**
决定：两次运行之间被跳过的天永远不会成行（实测 2026-09-05~09-09、09-11~09-14 全缺，
而 ledger 里这些天都有量）。数据源本身支持任意天重建，缺的只是窗口这一步。

本模块把窗口显式化，供 CLI 调用：

- 显式 ``DAY``    → 只写那一天（历史洞按天补写用；ledger 里没有的天不写）。
- ``auto``        → 写「上次快照日之后 → ledger 最新日」之间所有**有事件**的天（升序）。
  两次运行之间被跳过的天因此自动补上；ledger 里零事件的天自然跳过。
- ``auto`` 无历史行 → 只写最新一天（首跑不回溯全史：ledger 有 1.3 万+ 事件，
  全量补会把内嵌 JSON 的 HTML 撑到几十 MB）。
- ``auto`` 上次快照日 == 最新日 → 只写最新一天（当天进行中的行可被反复刷新，幂等）。
"""

from __future__ import annotations

from collections.abc import Iterable

AUTO = "auto"


def plan_snapshot_days(
	ledger_days: Iterable[str],
	snapshotted_days: Iterable[str],
	requested: str | None = None,
) -> list[str]:
	"""返回本次要写快照的日列表（升序去重）。

	``ledger_days``       ledger 里出现过的天（可含空串/重复，此处归一）。
	``snapshotted_days``  已有 ``deploy_project_mode_*`` 行的天（取自 quality_validation.json）。
	``requested``         CLI 传入的 DAY；None/空/``auto`` 视为自动窗口。
	返回 ``[]`` 表示无可写天（调用方按原语义报 SKIP）。
	"""
	days = sorted({str(d) for d in ledger_days if str(d)})
	if not days:
		return []
	req = str(requested or "").strip()
	if req and req != AUTO:
		return [req] if req in days else []
	latest = days[-1]
	seen = sorted({str(d) for d in snapshotted_days if str(d)})
	if not seen:
		return [latest]
	last = seen[-1]
	window = [d for d in days if d > last]
	# window 非空时最后一项必为 latest；为空 ⇒ last 已是 ledger 最新日，写它以刷新当天。
	return window or [latest]
