"""契约导出器的测试：生成的东西必须是"生产者真的会发"的东西。

五道：

1. **新鲜度**：改了枚举没重导 ⇒ 红。否则 GUI 那道门读的是过期清单，等于没有。
2. **扫描口径**：``add_gap`` 的原因码必须被扫到（漏扫就是门失效），且每个边界都仍在清单里。
3. **两套 state 词表不得互相冒充**：``_SHOWN_TEXT`` 是"送达状态"的正本；
   ``_required_action_unmet`` 那套是另一码事。出现第三个词表值就说明有人在往
   送达判定里塞不属于它的状态。
4. **投影旗标不得有人算、没人读**：引擎写下的每一类 ``invariant_errors`` 都必须被某条
   规则消费，否则事实静默丢失（见文件末尾那条测试的来历）。
5. **每个缺项原因码都要有报告侧的中文说法**：同一份事实有两个出口（界面与 markdown
   正文），只补一边就是让另一边把机器名印给人读。
"""

from __future__ import annotations

import re
from pathlib import Path

from diagnostics import export_contract as ec
from diagnostics import fault_split, identity

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


def test_every_emitted_gap_reason_has_a_report_label() -> None:
	"""缺项原因码在报告侧必须有人读说法 —— 界面的词表补齐过，正文的没有。

	``gap_reason_text`` 的兜底是「未归类原因（xxx）」：它不撒谎，但 markdown 报告与
	界面是同一份事实的两个出口。GUI 侧的 ``GAP_REASON_LABEL`` 在真实载荷上被"撞上了
	才补"过两次，python 侧实测 22 个 (边界, 原因) 里有 6 个直接印出机器名
	（no_records / unattributed_rows / not_comparable / not_found_in_full_file /
	recovered_outside_window / field_missing）。这条门把 python 侧钉住。
	"""
	contract = ec.collect_contract()
	reasons = sorted({g["reason"] for g in contract["gapReasons"]})
	assert reasons, "扫描口径失效：一个原因码都没扫到，这条门会静默全绿"
	for reason in reasons:
		label = identity.GAP_REASON_TEXT.get(reason)
		assert label, f"缺项原因码 {reason} 在报告侧没有中文说法"
		assert not re.search(r"[a-z]+_[a-z]+", label), f"{reason} 的中文说法里混了机器名：{label}"


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


#: 诊断夹具里带取值语义的字段名（会话/轮次/请求 id 这类自由字符串不在内）。
_FIXTURE_KEYS = ("kind", "error_kind", "error_code", "status", "code", "outcome", "cost_source", "note_kind", "body_state")
_STR_LIT = r'"([A-Za-z0-9_.\-]{3,32})"'
#: 生产者用 f-string 拼出来的取值：字面量不在源码里，但确实会写进审计行。
#: 这里按 (键, 值) 精确列，不用正则 —— 正则能被放宽成 ".*" 而当场看不出差别，
#: 清单扩大必须是一次显式的改动。
_COMPOSED_VALUES: set[tuple[str, str]] = {
	("error_code", "HTTP_400"),  # engine/query_loop.py: f"HTTP_{exc.status_code}"
}


def _non_test_literal_set() -> set[str]:
	root = _ROOT / "python"
	rx = re.compile(_STR_LIT)
	out: set[str] = set()
	for path in root.rglob("*.py"):
		rel = path.relative_to(root).as_posix()
		if ".venv" in rel or rel.startswith("tests/"):
			continue
		out.update(rx.findall(path.read_text(encoding="utf-8", errors="replace")))
	return out


def test_diagnostic_fixtures_only_use_values_a_producer_writes() -> None:
	"""诊断夹具的取值必须有出处；"看起来合理的枚举"不算证据。

	2026-09-25 登记过这条族（``test_rules_calibration`` 第 11 条）：单测自己写审计行 dict，
	于是"规则读一个生产端从没写过的字段"能长期全绿。2026-09-26 在同一族里又抓到三个我自己
	写的漂亮值 —— error_kind 写成 EXIT_NONZERO（真实 16 229 行 tool.finished 里非空
	error_kind 129/129 都是 INTERNAL）、code 写成 conn（真实只有 rate_limit /
	provider_error / network）。这里把"取值也要有出处"变成机器门。

	注意这条门扫的是整个文件的字面量，所以本段说明里不能再写键=值的字面形式，
	否则它会把散文当成用例红一次（第一次跑就红在这里，算它自证有效）。

	范围只钉 tests/diagnostics：同一口径扫整个 tests/ 另有 6 处落在别的工作流里
	（coord 的三种协调消息类型、控制面用例的大写枚举成员名、诊断工具的 ruff 码、
	多代理用例的自造 ping 类型）。那六条不归本流改，留在这里说明为什么门不做全仓。
	"""
	literals = _non_test_literal_set()
	assert len(literals) > 1000, f"字面量扫描口径失效：只读到 {len(literals)} 条（这条门会静默全绿）"
	dict_rx = {key: re.compile(rf'"{key}"\s*:\s*{_STR_LIT}') for key in _FIXTURE_KEYS}
	assign_rx = {key: re.compile(rf"\b{key}\s*=\s*{_STR_LIT}") for key in _FIXTURE_KEYS}
	checked = 0
	composed_hits: set[tuple[str, str]] = set()
	bad: list[str] = []
	for path in sorted((_ROOT / "python" / "tests" / "diagnostics").glob("*.py")):
		text = path.read_text(encoding="utf-8", errors="replace")
		for lineno, line in enumerate(text.split("\n"), 1):
			for key in _FIXTURE_KEYS:
				for rx in (dict_rx[key], assign_rx[key]):
					for match in rx.finditer(line):
						value = match.group(1)
						checked += 1
						if value in literals:
							continue
						if (key, value) in _COMPOSED_VALUES:
							composed_hits.add((key, value))
							continue
						bad.append(f"{path.name}:{lineno} {key}={value!r}")
	assert checked > 100, f"没读到夹具取值，扫描口径失效：{checked}"
	# 豁免清单必须"挣到自己那份活"，两个方向都钉：漏一项就当没记过，
	# 多一项（含放宽成正则的企图）就是有人在不看证据的情况下扩大豁免。
	assert composed_hits == _COMPOSED_VALUES, (
		f"拼值豁免与实际命中不一致：清单={sorted(_COMPOSED_VALUES)} 实际={sorted(composed_hits)}"
	)
	assert not bad, "这些夹具取值没有任何生产者写得出：" + "; ".join(bad[:10])


#: 诊断层从审计/转录/账本行里读键的几种写法（本仓库的采集与规则只用这几形）。
_READ_KEY_RX = re.compile(
	r'(?:row|att|event\.row|manifest|job|payload|item)\.get\("([a-z_][a-z0-9_]{2,28})"\)'
	r'|_kv\([a-z_]+, "([a-z_][a-z0-9_]{2,28})"\)'
)
_WRITE_KEY_RXS = (
	re.compile(r"\b([a-z_][a-z0-9_]{2,28})\s*=\s*[^=]"),
	re.compile(r'"([a-z_][a-z0-9_]{2,28})"\s*:'),
	re.compile(r'\["([a-z_][a-z0-9_]{2,28})"\]\s*='),
)


def test_every_field_the_diagnostics_layer_reads_has_a_writer() -> None:
	"""诊断读的那个键，产品源码里必须真的出现过。

	这一族在本项目里犯过 6 次以上（test_rules_calibration 第 11、13 条）：规则读一个
	生产者从不写（或叫别的名字）的字段，套件全绿而规则恒不命中。今天实测 55 个读键
	全部有出处，于是把这句话钉成机器门 —— 只改一侧的重命名当场就红。
	门只保证"键名在产品源码里存在"，不保证语义相同（那要靠走真实生产者的 roundtrip 用例）。
	"""
	python_root = _ROOT / "python"
	written: set[str] = set()
	files = 0
	for path in python_root.rglob("*.py"):
		rel = path.relative_to(python_root).as_posix()
		if ".venv" in rel or rel.startswith("tests"):
			continue
		files += 1
		text = path.read_text(encoding="utf-8", errors="replace")
		for rx in _WRITE_KEY_RXS:
			written.update(rx.findall(text))
	assert files > 300 and len(written) > 1000, f"写侧扫描口径失效：{files} 个文件 / {len(written)} 个键"

	missing: list[str] = []
	reads = 0
	for path in sorted((python_root / "diagnostics").glob("*.py")):
		text = path.read_text(encoding="utf-8", errors="replace")
		for lineno, line in enumerate(text.split("\n"), 1):
			for match in _READ_KEY_RX.finditer(line):
				key = match.group(1) or match.group(2)
				reads += 1
				if key not in written:
					missing.append(f"{path.name}:{lineno} {key}")
	assert reads > 40, f"读侧一条都没扫到，口径失效：{reads}"
	assert not missing, f"这些字段被诊断读、产品里却没人写：{missing[:10]}"


def test_coverage_sources_are_the_ones_the_collector_actually_builds() -> None:
	"""采集覆盖表的来源清单按字面量钉死，正则口径漂走时这条会红。

	期望写成字面量而不是"扫到就算对"：少扫一档就等于界面上少一档中文而没人报警。
	这 8 档与 2026-09-26 真实载荷里 coverage() 的键逐一对得上。
	"""
	assert ec.scan_coverage_sources() == [
		"audit",
		"captures",
		"fold_events",
		"jobs",
		"transcript",
		"usage",
		"wire_drops",
		"working",
	]
