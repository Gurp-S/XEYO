"""WSC 折叠评估的软水位与停止规则（旁路；``XEYO_WSC_SOFT_WATERMARK=0`` 时逐字不改现行为）。

存在的理由：现网折叠节奏由 ``memory/runtime.py`` 的 decoupled 支每枪问一次 θ 门决定，
而 θ 的判据里**没有任何"上下文够大了才值得考虑折叠"这一项**。注意不要认错人：
`LEVEL_WATERMARK`（`synaptic/types.py:37`）**在生产里一个读者都没有**（只剩定义 +
`synaptic/__init__.py` 的再导出），`XEYO_WSC_CADENCE_ABSORB` 那块读的是
`synaptic.cadence.watermark_tokens`，且该旗标默认关 ⇒ 两者都管不到现网节奏。
本模块把"什么时候才进入候选评估"独立出来，按裁定实现成**触发线**，不是目标大小。
候选门统一由 ``try_extend_c2`` 调用，覆盖两条普通扩展入口；HardTop 强制扩展绕过它。

裁定逐字落地（顾问 2026-09-30）：

1. 软水位只作**完整请求进入候选评估的触发线**，不兼任折叠后的目标大小 ⇒
   折完仍超线也算合格结果，本模块**不**要求"继续折到线以下"。
2. 每枪最多精算一个候选；本模块只回答"这一枪准不准进评估"。
3. 候选身份 =（冻结头版本, 可吸收边界, 消息修订状态）⇒ 相同候选不重复精算。
4. 重评估沿用 ``params.min_middle_edit_gap``（现值 4），且**从最近一次精算起算，
   包括被拒的那次**。
5. 评估枪号与成功折叠枪号分开记：本模块**绝不**读写 ``turns_since_c2`` /
   ``compact_cursor``，那两样是折叠侧的账。

硬容量压力（``d.hardtop``）由调用方绕开本模块——必要性高于节奏。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_ENV = "XEYO_WSC_SOFT_WATERMARK"
#: 顾问给的旁路初值。**是实验起点，不是已证明的注意力最优值**：32k/48k/64k 的扫描
#: 只能用来比较，不能单靠费用选数。默认 0 = 关闭 = 现行为。
DEFAULT_EXPERIMENT_TOKENS = 48_000

#: 拒绝原因（对外只认这四个）。
REASON_OK = "admit"
REASON_DISABLED = "gate_off"
REASON_BELOW = "below_soft_watermark"
REASON_SAME_CANDIDATE = "same_candidate"
REASON_COOLDOWN = "assessment_cooldown"


def soft_watermark_tokens() -> int:
	"""软水位（token）。0 = 关闭本模块 ⇒ 生产行为逐字不变。"""
	raw = os.environ.get(_ENV, "").strip()
	if not raw:
		return 0
	try:
		value = int(float(raw))
	except ValueError:
		return 0
	return value if value > 0 else 0


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
