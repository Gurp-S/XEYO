"""契约导出器的测试：生成的东西必须是"生产者真的会发"的东西。

三道：

1. **新鲜度**：改了枚举没重导 ⇒ 红。否则 GUI 那道门读的是过期清单，等于没有。
2. **扫描口径**：``add_gap`` 的原因码必须被扫到（漏扫就是门失效），且每个边界都仍在清单里。
3. **两套 state 词表不得互相冒充**：``_SHOWN_TEXT`` 是"送达状态"的正本；
   ``_required_action_unmet`` 那套是另一码事。出现第三个词表值就说明有人在往
   送达判定里塞不属于它的状态。
"""

from __future__ import annotations

import re
from pathlib import Path

from diagnostics import export_contract as ec
from diagnostics import fault_split

_ROOT = Path(__file__).resolve().parents[3]
_CONTRACT_PATH = _ROOT / "gui" / "src" / "generated" / "diagContract.ts"

#: `_required_action_unmet` 自己的词表：与"是否送达模型"无关，刻意不进 GUI 的送达徽章表。
UNMET_VOCABULARY = {
	"action_missing",
	"blocked_by_permission",
	"permission_outcome_unrecorded",
	"found",
	"absent",
}


def test_committed_contract_is_up_to_date() -> None:
	"""改了生产者枚举却忘了重导 ⇒ 必须在这里红，而不是让 GUI 的门读旧清单。"""
	expected = ec.render(ec.collect_contract())
	committed = _CONTRACT_PATH.read_text(encoding="utf-8")
	assert committed == expected, (
		"gui/src/generated/diagContract.ts 已过期：在 python/ 下跑 "
		"`py -3.11 -m diagnostics.export_contract` 并把生成文件一起提交"
	)


def test_scan_reaches_every_boundary_the_producer_can_emit() -> None:
	contract = ec.collect_contract()
	boundaries = {b["name"] for b in contract["boundaries"]}
	gap_boundaries = {g["boundary"] for g in contract["gapReasons"]}
	assert gap_boundaries, "一条缺项都没扫到：说明 add_gap 的正则口径变了"
	assert gap_boundaries <= boundaries, gap_boundaries - boundaries
	# 本会话修过的两个新码必须在清单里：它们在 GUI 里有中文，门才钉得住。
	assert {"recovered_outside_window", "not_found_in_full_file"} <= {
		g["reason"] for g in contract["gapReasons"]
	}


def test_shown_state_comparisons_stay_inside_the_two_vocabularies() -> None:
	"""送达判定的分支值必须都在正本里；只允许已知的另一套词表出现。"""
	compared: set[str] = set()
	for path in ec._py_sources():
		text = path.read_text(encoding="utf-8", errors="replace")
		compared.update(ec._SHOWN_STATE_RX.findall(text))
	unknown = compared - set(fault_split._SHOWN_TEXT) - UNMET_VOCABULARY
	assert not unknown, f"新出现的 state 值没有归属词表：{sorted(unknown)}"


def test_parties_have_labels_at_the_source() -> None:
	contract = ec.collect_contract()
	assert contract["parties"] == sorted(fault_split.PARTY_LABEL)
	for party in contract["parties"]:
		label = fault_split.PARTY_LABEL[party]
		assert label and label != party
		# 机器枚举不得混进人读正文（fault_split 顶部注释里的约束）。
		assert not re.search(r"[a-z]+_[a-z]+", label), f"{party} 的中文说法里混了机器名：{label}"
