"""观测 / 守卫调用的异常隔离（2026-09-14 事故的结构性防线）。

背景
----
``query_loop`` 热路径上有一族"只观测、不决策"的调用：``LoopLedger.observe_*``
（行为账本 s1/s2/s3）、``RepeatCallGuard.observe``（同签名提醒）、
``ZeroHitTracker.record``（空结果计数）。它们只写入诊断状态、供后续 T_now
渲染消费，**不参与**当前 turn 的执行决策。

事故形态（2026-09-14，sess_mu0mkitk_5aehjt）
--------------------------------------------
账本调用点误传原始 params（dict）→ callee 抛 ``TypeError: unhashable type``
→ 该异常与相邻的折叠动作（``IdenticalResultFold.process``，真正的止血阀）
共用一个 ``try`` / 裸 ``except Exception: pass`` 被一起吞掉 → 折叠在整条
会话上一次都没生效（同签名同输出空转 168 次，上下文 0→93k）。

结构性防线
----------
观测 / 守卫调用一律经 :func:`safe_observe` 包裹：任何异常只落 ``debug`` 日志、
返回 ``default``，**绝不**传播进主链路；且**绝不**与防护动作共用一个 try。
护栏是执行层机制（隔离 + fail-open），不是往注意力塞文本。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

_log = logging.getLogger(__name__)

_T = TypeVar("_T")


def safe_observe(
	call: Callable[..., _T],
	/,
	*args: Any,
	label: str,
	default: Any = None,
	**kwargs: Any,
) -> Any:
	"""在热路径上调用观测 / 守卫函数；异常只记 ``debug`` 日志并返回 ``default``。

	``label`` 是日志里的调用点名（如 ``"LoopLedger.observe_tool"``），
	用于定位哪一处接线失败——**禁止静默**（事故教训：裸 ``pass`` 让整条
	防护线失联 ~33 分钟无人察觉）。
	"""
	try:
		return call(*args, **kwargs)
	except Exception:  # noqa: BLE001 — 观测失败绝不挡主链路
		_log.debug("observe failed: %s", label, exc_info=True)
		return default