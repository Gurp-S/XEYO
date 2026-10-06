"""折叠冷却的**真否决**（A1 默认开、A2 常数档默认关；关掉 A1 即回到"只记账"的历史行为）。

## 它修什么

`memory.runtime.try_extend_c2` 第 4/5 条闸算出"这次折叠要 N 枪回本"并写进
``working.c2_gap_shots``（介质：sidecar 持久化、发射侧 ``CadenceState.adopt_gap``），
但**从不拿它拦下一次折叠**——2026-09-30 本地账本的真实 sess_ 会话中，85 对
上一折 gap_next>0 的相邻折叠有 81 对落在所记录间隔以内，实际间隔中位 4 枪，
记录间隔中位 20 枪。当天 DeepSeek turn 请求的 token 加权命中率为 90.054%
（477 请求，cached prompt / total prompt），账本成本是估价，非实付凭证。

## 两个旗标（分开量，才能看清哪一刀带来哪份收益）

- ``XEYO_WSC_FOLD_COOLDOWN_VETO``（布尔，**默认 1**）：把本会话**估算**的
  ``c2_gap_shots``（∈[MIN_GAP_SHOTS, effective_gap_cap()]）从记账改成真否决 ——
  「回本 N 枪内不再折」。置 ``0`` 即回到"只记账不否决"。
- ``XEYO_WSC_FOLD_MIN_INTERVAL``（数值，默认 0=关）：固定最小间隔 N 枪，
  不看回本实测。用来扫"常数档"与"实测档"的差别（数值键按既有惯例不进
  `memory_switches` 注册表——表行形状装不下一个整数；守卫测试的豁免写成等式）。

## 方向保证

两个闸都只**收紧**：命中即拒绝，拒绝发生在任何写之前（调用方
``try_extend_c2`` 的 ``_exit`` 只写只读出口 account）⇒ 游标/摘要/冷却数字
一个都不动。``force=True``（HardTop 必要性折叠）不受约束——必要性通道没有
"划算/节奏"可言（与 ``cooling`` 对 hardtop 的豁免同一口径）。

## 为什么现在默认开（2026-09-30）

θ=1 允许最多约 30 次后续请求回本，**不保证**折叠当次便宜。旧注释
误把它当成当次盈亏平衡，再推出"再等 N 枪只会把原文多发几遍"。同语料重放（
``_wsc_out/_fold_veto_ab.py``，6 份臂 × 6 份真实转录，off 臂在两张价目表上都比
A1 贵）。所以默认从"只记账"改成"真否决"：

* **历史离线证据**：折数 251→84（−67%）、miss token −20.8%、静态输入估价 −15.0%、
  命中率 +2.06pt；这些是历史版本的估算回放，未包含真实 system/tools 和容量强制折叠，
  不代表修复后的真实命中率或实付节省。当前版本配对产物见 `_wsc_out/repair_cooldown_*.jsonl`。
* **付掉的**：单枪尺寸上抬（总量 prompt +7.4%、峰值最多 2.7×）——因为折得少，
  未压缩段更长。要买回尺寸用现成的 ``XEYO_C2_GAP_CAP``（cap=8 档：钱 −12.2%、
  总量 −5.3%、命中 +0.71pt），不需要新常数。
* **回退**：``XEYO_WSC_FOLD_COOLDOWN_VETO=0``（逐字回到历史行为）。
"""

from __future__ import annotations

import os

#: 布尔旗标：实测冷却（`working.c2_gap_shots`）从记账改成真否决。
_ENV_COOLDOWN = "XEYO_WSC_FOLD_COOLDOWN_VETO"
#: 数值旗标：相邻两次折叠之间的固定最小枪数（未设/非数/≤0 = 关）。
_ENV_MIN_INTERVAL = "XEYO_WSC_FOLD_MIN_INTERVAL"


def cooldown_veto_enabled() -> bool:
	"""A1 开关。读法与其它 WSC 策略旗标同一份（``memory_switches.env_flag``）。"""
	try:
		from memory.memory_switches import env_flag

		return bool(env_flag(_ENV_COOLDOWN))
	except Exception:  # noqa: BLE001 — 判不出来就当关（旁路默认态）
		return False


def min_interval_shots() -> int:
	"""A2 间隔枪数。fail-open：解析失败/≤0 一律 0（=关），**绝不因为写错参数而多折**。"""
	raw = (os.environ.get(_ENV_MIN_INTERVAL) or "").strip()
	if not raw:
		return 0
	try:
		n = int(float(raw))
	except (TypeError, ValueError):
		return 0
	return max(0, n)


def evaluate(*, turns_since_c2: int, c2_gap_shots: int) -> tuple[str, dict]:
	"""返回 ``(否决理由, 判据数字)``；放行时 ``("", {})``。

	理由只用于账本分辨哪一刀生效：A1 ``cooldown_veto``、A2 ``min_interval_veto``。
	两者同开时先判 A1（实测档优先），A2 只补位。
	"""
	try:
		since = max(0, int(turns_since_c2 or 0))
	except (TypeError, ValueError):
		since = 0
	try:
		gap = max(0, int(c2_gap_shots or 0))
	except (TypeError, ValueError):
		gap = 0
	# since 包含折叠当次请求；N 次后续复用全部结束时才有 since=N+1。
	if cooldown_veto_enabled() and gap > 0 and since <= gap:
		return "cooldown_veto", {
			"turns_since_c2": since,
			"c2_gap_shots": gap,
			"veto_min_interval": min_interval_shots(),
		}
	n = min_interval_shots()
	if n > 0 and since < n:
		return "min_interval_veto", {
			"turns_since_c2": since,
			"c2_gap_shots": gap,
			"veto_min_interval": n,
		}
	return "", {}
