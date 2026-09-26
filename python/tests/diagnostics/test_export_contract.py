"""契约导出器的测试：生成的东西必须是"生产者真的会发"的东西。

四道：

1. **新鲜度**：改了枚举没重导 ⇒ 红。否则 GUI 那道门读的是过期清单，等于没有。
2. **扫描口径**：``add_gap`` 的原因码必须被扫到（漏扫就是门失效），且每个边界都仍在清单里。
3. **两套 state 词表不得互相冒充**：``_SHOWN_TEXT`` 是"送达状态"的正本；
   ``_required_action_unmet`` 那套是另一码事。出现第三个词表值就说明有人在往
   送达判定里塞不属于它的状态。
4. **投影旗标不得有人算、没人读**：引擎写下的每一类 ``invariant_errors`` 都必须被某条
   规则消费，否则事实静默丢失（见文件末尾那条测试的来历）。
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
	"commands_unrecorded",
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


def test_session_constant_gaps_are_a_consistent_subset() -> None:
	"""会话级缺项必须是"生产者确实会发"的子集，且与 collect 的声明一一对应。

	钉两件事：① 界面按 scope 折叠的那几条，生产者今天确实发得出来（否则界面上永远
	等不到，折叠逻辑是死码）；② collect.SESSION_CONSTANT_GAPS 里若混进一个发不出的
	(边界, 原因) 拼写，这里当场红，而不是悄悄掉出去让会话块少一项。
	"""
	contract = ec.collect_contract()
	emitted = {(g["boundary"], g["reason"]) for g in contract["gapReasons"]}
	declared = ec.collect.SESSION_CONSTANT_GAPS
	session = {(g["boundary"], g["reason"]) for g in contract["sessionConstantGaps"]}
	assert session <= emitted, session - emitted
	# 声明的每一项都要么被发出、要么显式承认发不出；不允许拼错导致静默漏项。
	assert declared <= emitted, f"声明为会话级但生产者发不出：{sorted(declared - emitted)}"
	assert session == declared


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


#: 引擎投影旗标的正本清单（engine/projection_manifest.py 写下的四类）。
INVARIANT_VOCABULARY = {
	"unresolved_tool_calls",
	"orphan_tool_results",
	"truncation_without_handle",
	"canonical_unpaired_tool_calls",
}


def test_every_projection_invariant_flag_is_claimed_by_a_rule() -> None:
	"""生产者算出来的旗标没有规则读，界面上就永远显示"没有这类问题"。

	``canonical_unpaired_tool_calls`` 正是这么被漏掉的：引擎每次投影都在算它，
	规则集里却无人读它 ⇒ 已经拿到的事实整条丢失。这里钉两个方向 ——
	写了没人读要红；读了却没人写，只可能是判据改版前留在磁盘上的旧旗标（显式登记）。
	"""
	scan = ec.scan_invariant_names()
	assert set(scan["written"]) == INVARIANT_VOCABULARY, (
		f"引擎侧旗标清单对不上：{scan['written']} —— written 为空说明扫描口径失效（门会静默全绿）"
	)
	assert not scan["unclaimed"], f"这些旗标没有任何规则读，界面上等于不存在：{scan['unclaimed']}"
	# 这一条按字面钉死，不从 LEGACY_INVARIANT_NAMES 推：把豁免清单改小应当是一次
	# 有意识的决定，而不是跟着常量一起静默变绿。
	assert scan["legacy_read"] == ["spill_reference_mismatch"]
