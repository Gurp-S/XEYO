"""续跑指令（[Resume] 契约）投影-only 通道。

设计 32 修订 2：续跑富化指令不再落库成真实 user 消息——JSONL/历史只存
用户真实文本（如「继续」），富化指令经 ``submit_options["resume_directive"]``
传入引擎，由 T_now 注入管线在本轮每次 model 调用前送达（env_channel 下随
伪造对走环境声道，legacy 下随尾插——两种声道都不落库）。轮结束即清。

治理目标：跨任务锚定——旧任务的续跑指令以用户身份永久留在历史里，会在
后续新任务中被模型重新读取（L543 事故同族）。
"""

from __future__ import annotations

from contextvars import ContextVar

_cv: ContextVar[str | None] = ContextVar("xeyo_resume_directive", default=None)


def set_resume_directive(text: str) -> None:
	"""本轮续跑富化指令（turn 内每次 model 调用可见；不落库）。"""
	v = (text or "").strip()
	_cv.set(v or None)


def get_resume_directive() -> str:
	"""当前轮的续跑指令；无则空串。"""
	return str(_cv.get() or "")


def clear_resume_directive() -> None:
	_cv.set(None)
