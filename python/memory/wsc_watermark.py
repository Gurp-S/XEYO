"""WSC 折叠评估的候选门（**绝对水位旋钮已退场**，2026-10-08 用户裁定）。

退场后本模块只负责"这一枪准不准进入候选评估"的状态机（候选身份去重 / 评估冷却），
不再从环境读水位：新机制 ``memory/wsc_timing`` 的判据明令"绝对 token 水位不得放行
自动折叠"，唯一自动通路是容量压力（≥ 声明容量的 85%）。因此
:func:`soft_watermark_tokens` 恒返回 0，调用点的水位门自然短路；只有显式传
``watermark`` 的调用者才存在闸门（测试与离线实验用）。

其余历史设计（候选身份三要素 / 冷却从最近一次精算起算 / 评估枪号与折叠枪号分开 /
硬容量压力绕开本模块）继续有效。
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 旋钮 ``XEYO_WSC_SOFT_WATERMARK`` 已退场（2026-10-08 用户裁定）：新机制
#: ``memory/wsc_timing`` 的判据明令"**绝对 token 水位不得放行自动折叠**"，唯一
#: 自动通路是容量压力（≥ 声明容量的 85%）。本模块保留候选评估的状态机
#: （候选身份去重 / 评估冷却），但不再从环境取水位——只有调用方显式传
#: ``watermark`` 才存在闸门；生产调用点不再传（见 ``memory/runtime``）。

#: 拒绝原因（对外只认这四个）。
REASON_OK = "admit"
REASON_DISABLED = "gate_off"
REASON_BELOW = "below_soft_watermark"
REASON_SAME_CANDIDATE = "same_candidate"
REASON_COOLDOWN = "assessment_cooldown"


def soft_watermark_tokens() -> int:
	"""软水位（token）。**退场后恒 0** ⇒ 不按绝对水位放行折叠。

	历史：本函数原读 ``XEYO_WSC_SOFT_WATERMARK``（旁路实验起点值 32k/48k/64k）。
	该键退役后，自动折叠只由 ``memory/wsc_timing`` 的容量压力触发；这里返回 0
	让调用点的水位门自然短路（与"默认关"的历史默认值一致）。
	"""
	return 0


@dataclass
class _SessionAssessments:
	"""一个会话的评估台账（进程内）。刻意不碰 ``WorkingSnapshot``。"""

	shots: int = 0
	last_shot: int = -10**9
	last_identity: str = ""
	#: 观测用：各类拒绝各发生了几次。
	counts: dict[str, int] = field(default_factory=dict)


_STATE: dict[str, _SessionAssessments] = {}
_MAX_STATE = 64


def candidate_identity(*, head_version: str, region_end: int, revision_state: str) -> str:
	"""候选身份。三要素缺一不成立：

	- ``head_version``：冻结头的字节版本（调用方给 seal / 头文本摘要都行）；
	- ``region_end``：可吸收边界（切点变了就是另一个候选）；
	- ``revision_state``：消息修订状态。**不能只比消息条数**——原地改写与回滚
	  都不改条数，却会造出新候选（顾问明令）。
	"""
	return f"{head_version}|{int(region_end)}|{revision_state}"


def admit_assessment(session_id: str, *, input_tokens: int, identity: str,
                     min_gap_shots: int = 4, watermark: int | None = None) -> str:
	"""这一枪准不准进入折叠候选评估。返回 ``REASON_*`` 之一。

	``input_tokens`` 必须是**完整请求**的 token（固定提示 + 头 + 尾 + 工具定义），
	不是头的长度。估算口径由调用方负责统一（本模块不换算、不猜窗口）。
	"""
	limit = soft_watermark_tokens() if watermark is None else int(watermark)
	if limit <= 0:
		return REASON_DISABLED
	state = _STATE.get(session_id)
	if state is None:
		if len(_STATE) >= _MAX_STATE:
			_STATE.pop(next(iter(_STATE)))
		state = _STATE[session_id] = _SessionAssessments()
	state.shots += 1
	reason = REASON_OK
	if int(input_tokens) < limit:
		reason = REASON_BELOW
	elif identity and identity == state.last_identity:
		reason = REASON_SAME_CANDIDATE
	elif state.last_shot >= 0 and state.shots - state.last_shot < max(0, int(min_gap_shots)):
		reason = REASON_COOLDOWN
	if reason == REASON_OK:
		# 只有**真的进入精算**才登记身份与枪号；被水位挡下的不算一次精算。
		state.last_identity = identity
		state.last_shot = state.shots
	state.counts[reason] = state.counts.get(reason, 0) + 1
	return reason


def reset_session(session_id: str) -> None:
	"""测试/会话结束用。生产路径不依赖它（状态槽按 FIFO 逐出）。"""
	_STATE.pop(session_id, None)


def stats(session_id: str) -> dict[str, object]:
	state = _STATE.get(session_id)
	if state is None:
		return {"shots": 0, "counts": {}}
	return {"shots": state.shots, "last_shot": state.last_shot,
	        "last_identity": state.last_identity, "counts": dict(state.counts)}
