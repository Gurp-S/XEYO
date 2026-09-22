# -*- coding: utf-8 -*-
"""问答集判定器的自证测试：每条判据都要有**正例 / 负例 / 判不了**三种夹具。

为什么这组测试比被测系统更重要：判定器一旦与投影渲染同源，臂间比较会**结构性**失效，
而失效的表现形式是「数字看起来更好」。这里把四种已发生过的失效模式各钉一条：

1. 合成串当针（投影把 ``error_sig`` 抄进热层 ⇒ 压缩臂自证）
   → ``test_synth_signature_alone_is_not_visible``
2. 单边归一化（历史事故：nocompress 臂被误判成 0.47）
   → ``test_single_sided_normalization_would_be_caught``
3. 缺数据当满分（历史事故：三个零错误会话各贡献 1.0 ⇒ 头条数 0.9583 是伪影）
   → ``test_missing_denominator_is_not_a_perfect_score``
4. 分子分母不同源（历史事故：F3 报出 ``11/6``，rate = 183%）
   → ``test_yes_over_total_is_rejected``

另有两条防悄悄退化的回归：锚点抽取的「先剥标点再量长度」与散文型失败的兜底针
（两者都是实测出来的假阴：上界臂被判成不可见）。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from synaptic.failure_modes import QUESTION_BANK, analyze, turn_facts
from synaptic.graph import build_graph
from synaptic.qa_grading import (
    Answer,
    aggregate,
    arm_symmetry_violations,
    make,
    question_bank_digest,
    wilson_ci,
)
from synaptic.qa_visibility import (
    Visibility,
    VisibilityLedger,
    _norm,
    anchors_for,
    fallback_anchor,
    judge,
    raw_anchors,
    synth_key,
    visible,
    visible_any,
)
from synaptic.textutil import message_text
from wsc._fixtures import synth_session

# ---------------------------------------------------------------------------
# 题库登记：每道题必须点到**存在的**测试函数，否则新增题目即红
# ---------------------------------------------------------------------------

COVERAGE: dict[str, tuple[str, ...]] = {
    "V1": ("test_visibility_answers_have_both_directions",),
    "V2": ("test_visibility_answers_have_both_directions",),
    "V3": ("test_synth_signature_alone_is_not_visible",
           "test_visibility_answers_have_both_directions"),
    "V4": ("test_visibility_answers_have_both_directions",),
    "V5": ("test_visibility_answers_have_both_directions",),
    "V6": ("test_todo_items_are_judged_when_present",),
    "E1": ("test_synth_signature_alone_is_not_visible",
           "test_visibility_answers_have_both_directions"),
    "E2": ("test_visibility_answers_have_both_directions",),
    "R1": ("test_repeat_and_invalid_turns_are_trajectory_dim",),
    "R2": ("test_repeat_and_invalid_turns_are_trajectory_dim",),
    "R3": ("test_r3_reports_retry_only_without_intervening_write",),
    "I1": ("test_repeat_and_invalid_turns_are_trajectory_dim",),
    "I2": ("test_i2_requires_a_prior_failure_and_no_write",),
    "I3": ("test_repeat_and_invalid_turns_are_trajectory_dim",),
    "F1": ("test_forbidden_actions_denominator_is_explicit",),
    "F2": ("test_forbidden_actions_denominator_is_explicit",),
    "F3": ("test_f3_is_a_count_not_a_rate",),
    "A1": ("test_artifact_answers_are_not_applicable_without_writes",),
    "A2": ("test_artifact_answers_are_not_applicable_without_writes",),
    "A3": ("test_artifact_answers_are_not_applicable_without_writes",),
    "A4": ("test_a4_is_external_truth_only",),
}

VALID_ANCHORS = {"goal_text", "constraint", "node_text", "path_ref", "todo_item",
                 "invocation", "none"}
VALID_UNITS = {"ratio", "count"}
VALID_DIMS = {"projection", "trajectory"}


def test_every_question_is_covered_by_a_real_test():
	"""题库准入：新增题目必须同时登记夹具（否则这道题没人证伪过）。"""
	ids = [q.id for q in QUESTION_BANK]
	assert len(ids) == len(set(ids)), "题号重复"
	assert set(COVERAGE) == set(ids), (f"未登记夹具的题: {sorted(set(ids) - set(COVERAGE))}；"
	                                   f"多余登记: {sorted(set(COVERAGE) - set(ids))}")
	names = set(globals())
	for qid, tests in COVERAGE.items():
		assert tests, f"{qid} 没有任何夹具"
		for name in tests:
			assert name in names, f"{qid} 指向不存在的测试函数 {name}"


def test_question_metadata_is_declared():
	for q in QUESTION_BANK:
		assert q.anchors in VALID_ANCHORS, q.id
		assert q.unit in VALID_UNITS, q.id
		assert q.dims in VALID_DIMS, q.id
		assert q.kind in ("mechanical", "sample"), q.id


# ---------------------------------------------------------------------------
# 失效模式 1：合成串当针
# ---------------------------------------------------------------------------


def test_synth_signature_alone_is_not_visible():
	"""投影把 ``error_sig`` 原样抄进热层时，主指标**不得**因此判可见。"""
	# 真实形状：PowerShell 把一条消息切成多行，合成签名（``_refine_sig`` 用 ": " 焊接）
	# 在原文里根本不存在；针取原文正文头部（兜底锚点）。
	raw_text = ("Chunk ID: 0a9f22\nWall time: 4.7565 seconds\nProcess exited with code 1\n"
	            "Output:\nhead: \r\nLine |\r\n   2 |  odules* -g \"!*.png\" | head -200\r\n")
	anchors = anchors_for(raw_text)
	assert anchors, "有实义正文就该建得出针"

	sig = "The term 'head' is not recognized as a name of a cmdlet, function, script file"
	projection_like = f"失败: {synth_key(sig)}"  # 模拟 assemble 的卡片行

	vis = judge(projection_like, raw=anchors, synth=sig)
	assert vis.synth_hit is True, "合成串确实命中（这正是要防的机制）"
	assert vis.raw_hit is False, "原文锚点不在合成串里 ⇒ 主指标必须判不可见"
	assert vis.synth_only is True

	led = VisibilityLedger()
	led.add(vis)
	assert (led.raw_yes, led.total, led.synth_only) == (0, 1, 1), "主指标不得被合成串抬起来"

	# 正例对照：真把原文放进去 ⇒ 主指标命中
	vis_raw = judge(raw_text + projection_like, raw=anchors, synth=sig)
	assert vis_raw.raw_hit is True and vis_raw.synth_only is False


def test_synth_key_is_not_a_raw_anchor():
	"""``synth_key`` 是**缩写**（去数字截断），不得混用成原文锚点。"""
	sig = "ParserError: $ok = 'x' at line 12345 unexpected token"
	key = synth_key(sig)
	assert key and key != sig
	# 原文里没有截断后的形态 ⇒ 合成口径会判不可见，原文锚点口径判可见
	assert visible(sig, key) is True
	assert any(visible(sig, a) for a in anchors_for(sig))


# ---------------------------------------------------------------------------
# 失效模式 2：单边归一化
# ---------------------------------------------------------------------------


def test_single_sided_normalization_would_be_caught():
	"""历史事故回归：只归一化一侧 ⇒ 原文臂被误判成不可见（实测 0.47）。"""
	raw = "chunk\r\nid\r\nNOT_FOUND: 404 for /api/v1/user"   # 原文带 CRLF
	needle = "NOT_FOUND: # for /api/v#/user"                 # 签名侧已折叠 + 数字归一
	assert visible(raw, needle) is True, "两侧同归一（空白折叠 + 数字→#）必须命中"

	def single_sided(text: str, query: str) -> bool:
		"""变异体：只归一化查询侧（历史 bug 的形态），夹具必须能抓住它。"""
		return bool(query) and _norm(query) in str(text)

	assert single_sided(raw, needle) is False, "夹具本身要有区分度"


def test_anchors_are_arm_symmetric_by_construction():
	"""同一条针在两条臂上必须走同一条判定路径（不同输入只影响命中，不影响口径）。"""
	cell = "ConfigError: missing key 'api.timeout' in config/app.yaml"
	anchors = anchors_for(cell)
	assert anchors
	full = f"prefix\n{cell}\nsuffix"
	assert visible_any(full, anchors) is True
	assert visible_any("", anchors) is False  # 空臂：漏报，而不是误报


# ---------------------------------------------------------------------------
# 锚点抽取的两种假阴（实测：上界臂被判成不可见）
# ---------------------------------------------------------------------------


def test_short_named_failures_still_get_a_needle():
	"""``ParserError:`` 剥掉冒号只剩 11 字符 ⇒ 本身不够格当锚点，必须靠兜底针。

	实测：这类失败一旦抽不出针，上界臂（原文全给）也会被判"不可见"。
	"""
	assert raw_anchors("ParserError: \r\nLine |\r\n") == ()
	assert anchors_for("ParserError: \r\nLine |\r\n") == ("ParserError: Line |",)
	# 够长的词块照收（剥标点不影响判定）
	assert "ResourceUnavailable" in raw_anchors("ResourceUnavailable: rg.exe failed to run")


def test_cjk_items_are_measured_by_information_not_by_char_count():
	"""中文按信息量算：``补齐超时回归测试``（8 字）是完整短语，不能被当"太短"。"""
	from synaptic.qa_visibility import info_len

	assert info_len("补齐超时回归测试") >= 12
	assert info_len("4.7565") < 12
	assert raw_anchors("补齐超时回归测试") == ("补齐超时回归测试",)


def test_prose_failures_get_a_fallback_anchor():
	"""散文型失败没有 ≥12 字符词块 ⇒ 退回正文头部兜底针，而不是"判不了"。"""
	text = ("Chunk ID: 0a9f22\nWall time: 4.7565 seconds\nProcess exited with code 1\n"
	        "Output:\nhead: \r\nLine |\r\nThe term 'head' is not recognized as a name\r\n")
	assert raw_anchors(text) == ()
	assert anchors_for(text), "兜底针必须建得出来"
	assert fallback_anchor(text).startswith("head:")
	assert visible_any(text, anchors_for(text)) is True


def test_unanchored_events_leave_the_denominator():
	"""判不了 ≠ 不可见：建不出针的事件移出分母，并单独计数。"""
	vis = judge("", raw=())
	assert vis.unanchored is True
	led = VisibilityLedger()
	led.add(vis)
	led.add(judge("", raw=anchors_for("Get-CimInstance: 拒绝访问")))
	assert led.total == 1 and led.raw_yes == 0 and led.unanchored == 1
	# 事实型判定（由轨迹自身决定，针就是事件本身）照常进分母
	led.add(Visibility(raw_hit=True))
	assert led.total == 2 and led.raw_yes == 1


# ---------------------------------------------------------------------------
# 失效模式 3 / 4：缺数据与分子分母
# ---------------------------------------------------------------------------


def test_missing_denominator_is_not_a_perfect_score():
	a = make("E1", "error_visibility", "q", "mechanical", 0, 0)
	assert a.status == "not_applicable"
	assert a.rate is None, "缺数据不得折算成任何数（历史事故：else 1.0）"
	assert a.row()["rate"] is None

	per_session = {
		"s_zero_1": {"E1": make("E1", "m", "q", "mechanical", 0, 0)},
		"s_zero_2": {"E1": make("E1", "m", "q", "mechanical", 0, 0)},
		"s_zero_3": {"E1": make("E1", "m", "q", "mechanical", 0, 0)},
		"s_a": {"E1": make("E1", "m", "q", "mechanical", 21, 22)},
		"s_b": {"E1": make("E1", "m", "q", "mechanical", 0, 0)},
		"s_c": {"E1": make("E1", "m", "q", "mechanical", 0, 0)},
	}
	rec = aggregate(per_session)["E1"]
	assert rec["total"] == 22 and rec["yes"] == 21
	assert abs(rec["rate"] - 0.9545) < 1e-3, "旧口径会把零分母会话算成 1.0（报出 0.9583）"
	assert rec["sessions_contributing"] == 1
	assert rec["skewed"] is True, "单会话扛 100% 分母 ⇒ 必须标偏斜"
	assert rec["gate_eligible"] is False


def test_yes_over_total_is_rejected():
	with pytest.raises(ValueError):
		Answer("F3", "forbidden_actions", "q", "mechanical", 11, 6)
	# 计数类显式声明后可以 yes > total（次数 / 暴露量），但不再冒充比例
	count = Answer("F3", "forbidden_actions", "q", "mechanical", 11, 6, unit="count")
	assert count.rate is None and count.density_per_1k == pytest.approx(1833.33, abs=0.01)


def test_no_metric_is_silently_capped_or_defaulted():
	"""静态执法：判定器源码里不得再出现 ``else 1.0`` 这类兜底满分（只看代码，不看注释）。"""
	import ast

	for mod in ("synaptic.failure_modes", "synaptic.qa_grading"):
		path = Path(__import__(mod, fromlist=["x"]).__file__)
		tree = ast.parse(path.read_text(encoding="utf-8"))
		bad = [n.lineno for n in ast.walk(tree)
		       if isinstance(n, ast.IfExp) and isinstance(n.orelse, ast.Constant)
		       and n.orelse.value == 1.0]
		assert bad == [], f"{path.name} 出现兜底满分（行 {bad}）"


def test_wilson_interval_narrows_with_more_samples_and_is_a_proper_interval():
	lo1, hi1 = wilson_ci(1, 10)
	lo2, hi2 = wilson_ci(100, 1000)
	assert lo2 > lo1 - 1e-9 and (hi2 - lo2) < (hi1 - lo1)
	assert 0.0 <= lo1 <= hi1 <= 1.0
	assert wilson_ci(0, 0) is None


# ---------------------------------------------------------------------------
# 臂对称检查本身
# ---------------------------------------------------------------------------


def test_arm_symmetry_flags_wsc_above_nocompress():
	per_arm = {
		"wsc": {"V3": {"rate": 0.7333, "total": 15}, "V1": {"rate": 1.0, "total": 6}},
		"nocompress": {"V3": {"rate": 0.4, "total": 15}, "V1": {"rate": 1.0, "total": 6}},
	}
	viol = arm_symmetry_violations(per_arm)
	assert [v["qid"] for v in viol] == ["V3"]
	assert arm_symmetry_violations(per_arm, whitelist=("V3",)) == []


def test_question_bank_digest_tracks_edits():
	d0 = question_bank_digest(QUESTION_BANK)
	edited = (dataclasses.replace(QUESTION_BANK[0], rule="改过的规则"),) + tuple(QUESTION_BANK[1:])
	assert question_bank_digest(edited) != d0


# ---------------------------------------------------------------------------
# 端到端：合成轨迹 × 三条臂
# ---------------------------------------------------------------------------


def _arms(msgs: list[dict]) -> tuple[dict, dict, object]:
	graph = build_graph(msgs, include_soft_edges=False)
	facts = turn_facts(graph, msgs, len(msgs))
	full = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
	empty = {tf.turn: "" for tf in facts}
	err = next((n for n in graph.nodes if n.is_error and n.error_sig), None)
	only_sig = {tf.turn: f"失败: {synth_key(err.error_sig)}" if err else "" for tf in facts}
	return {"graph": graph, "facts": facts, "full": full, "empty": empty, "sig": only_sig}, {}, graph


def test_visibility_answers_have_both_directions():
	fixtures, _, graph = _arms(synth_session(turns=5, error_turn=1, user_every=2))
	msgs = synth_session(turns=5, error_turn=1, user_every=2)
	graph = build_graph(msgs, include_soft_edges=False)
	full = analyze(msgs, graph, fixtures["full"], len(msgs))
	empty = analyze(msgs, graph, fixtures["empty"], len(msgs))
	for qid in ("V1", "V2", "V3", "V4", "V5", "E1", "E2"):
		a_full, a_empty = full.answers[qid], empty.answers[qid]
		assert a_full.total > 0, f"{qid} 正例没有分母"
		assert a_full.yes == a_full.total, f"{qid} 原文全给时应当全可见"
		assert a_empty.total > 0 and a_empty.yes == 0, f"{qid} 空臂应当全不可见（漏报）"
		assert a_empty.rate == 0.0 and a_empty.status == "measured"


def test_synth_signature_alone_is_not_visible_end_to_end():
	"""端到端不变量：**只渲染合成签名**的臂，主指标不得高于**给原文**的臂。

	这正是旧口径下 wsc 反超 nocompress 的机制（V3 15/15 vs 6/15）；主指标改成
	原文锚点后，签名渲染只应体现在 ``synth_only`` 列里。
	"""
	msgs = synth_session(turns=5, error_turn=1, user_every=2)
	graph = build_graph(msgs, include_soft_edges=False)
	facts = turn_facts(graph, msgs, len(msgs))
	err = next(n for n in graph.nodes if n.is_error and n.error_sig)
	sig_only = {tf.turn: f"失败: {synth_key(err.error_sig)}" for tf in facts}
	raw = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
	by_sig = analyze(msgs, graph, sig_only, len(msgs))
	by_raw = analyze(msgs, graph, raw, len(msgs))
	for qid in ("V3", "V4", "E1", "E2"):
		assert by_sig.answers[qid].yes <= by_raw.answers[qid].yes, f"{qid}: 签名渲染臂反超原文臂"
	# 注意：本夹具的签名里含真锚点（``AssertionError:`` 原文里就有）⇒ 判可见是**对的**，
	# ``synth_only`` 只在「渲染串推不出原文锚点」时点亮（见纯合成串的单测）。
	assert by_raw.answers["V3"].total >= 1 and by_raw.answers["V3"].yes == by_raw.answers["V3"].total


def test_todo_items_are_judged_when_present():
	msgs = synth_session(turns=4, error_turn=1, include_todo=True)
	graph = build_graph(msgs, include_soft_edges=False)
	facts = turn_facts(graph, msgs, len(msgs))
	full = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
	rep = analyze(msgs, graph, full, len(msgs))
	assert rep.answers["V6"].total >= 1, "有 TodoWrite 就该进分母"
	assert rep.answers["V6"].yes == rep.answers["V6"].total
	no_todo = synth_session(turns=4, error_turn=1, include_todo=False)
	g2 = build_graph(no_todo, include_soft_edges=False)
	f2 = turn_facts(g2, no_todo, len(no_todo))
	ctx2 = {tf.turn: "\n".join(message_text(m) for m in no_todo[:tf.region_end]) for tf in f2}
	rep2 = analyze(no_todo, g2, ctx2, len(no_todo))
	assert rep2.answers["V6"].status == "not_applicable"


def test_repeat_and_invalid_turns_are_trajectory_dim():
	"""``dims=trajectory`` 的题必须**与臂无关**（两侧同值），否则会在报告里被误读成差异。"""
	msgs = synth_session(turns=6, error_turn=1, user_every=2)
	graph = build_graph(msgs, include_soft_edges=False)
	facts = turn_facts(graph, msgs, len(msgs))
	full = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
	empty = {tf.turn: "" for tf in facts}
	a = analyze(msgs, graph, full, len(msgs))
	b = analyze(msgs, graph, empty, len(msgs))
	for qid in ("R1", "I1", "I2", "R3"):
		assert a.answers[qid].yes == b.answers[qid].yes, qid
		assert a.answers[qid].total == b.answers[qid].total, qid


def test_i2_requires_a_prior_failure_and_no_write():
	"""I2（白跑一轮）：先失败 → 原样重发（其间无写）= 命中；中间有写 ⇒ 不算（环境可能已变）。"""
	from wsc._fixtures import msg_asst_text, msg_asst_use, msg_tool, msg_user

	cmd = {"command": "npm test"}
	def build(with_write: bool) -> list[dict]:
		msgs = [msg_user("修一下测试"), msg_asst_use("u1", "Bash", cmd),
		        msg_tool("u1", "Bash", "FAILED suite_a\nAssertionError: boom", is_error=True),
		        msg_asst_text("重试")]
		if with_write:
			msgs += [msg_asst_use("w1", "Edit", {"path": "a.ts", "old_string": "x", "new_string": "y"}),
			         msg_tool("w1", "Edit", "edited")]
		msgs += [msg_user("继续"), msg_asst_use("u2", "Bash", cmd),
		         msg_tool("u2", "Bash", "FAILED suite_a\nAssertionError: boom", is_error=True)]
		return msgs

	def i2_yes(msgs: list[dict]) -> int:
		graph = build_graph(msgs, include_soft_edges=False)
		facts = turn_facts(graph, msgs, len(msgs))
		ctx = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
		rep = analyze(msgs, graph, ctx, len(msgs))
		return rep.answers["I2"].yes

	assert i2_yes(build(with_write=False)) >= 1, "无写操作的重复失败调用应当命中"
	assert i2_yes(build(with_write=True)) == 0, "中间有写 ⇒ 环境可能已变，不得判白跑"


def test_r3_reports_retry_only_without_intervening_write():
	from wsc._fixtures import msg_asst_text, msg_asst_use, msg_tool, msg_user

	inv = {"command": "pytest -k timeout"}
	def build(with_write: bool) -> list[dict]:
		msgs = [msg_user("修"), msg_asst_use("a1", "Bash", inv),
		        msg_tool("a1", "Bash", "E   ModuleNotFoundError: No module named 'x'", is_error=True),
		        msg_asst_text("再试")]
		if with_write:
			msgs += [msg_asst_use("w1", "Edit", {"path": "b.ts", "old_string": "1", "new_string": "2"}),
			         msg_tool("w1", "Edit", "edited")]
		msgs += [msg_asst_use("a2", "Bash", inv),
		         msg_tool("a2", "Bash", "E   ModuleNotFoundError: No module named 'x'", is_error=True)]
		return msgs

	def r3(msgs: list[dict]) -> tuple[int, int]:
		graph = build_graph(msgs, include_soft_edges=False)
		facts = turn_facts(graph, msgs, len(msgs))
		ctx = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
		a = analyze(msgs, graph, ctx, len(msgs)).answers["R3"]
		return a.yes, a.total

	yes, total = r3(build(with_write=False))
	assert total >= 1 and yes >= 1
	yes_w, _ = r3(build(with_write=True))
	assert yes_w == 0


def test_forbidden_actions_denominator_is_explicit():
	"""``forbidden_actions = 0`` 必须能分辨「没有禁令」和「有禁令没违反」。"""
	from wsc._fixtures import msg_asst_use, msg_tool, msg_user

	msgs = [msg_user("只改 src/auth.ts，不要 commit"),
	        msg_asst_use("u1", "Edit", {"path": "src/auth.ts", "old_string": "a", "new_string": "b"}),
	        msg_tool("u1", "Edit", "edited"),
	        msg_asst_use("u2", "Bash", {"command": "git status"}),
	        msg_tool("u2", "Bash", "On branch main")]
	graph = build_graph(msgs, include_soft_edges=False)
	facts = turn_facts(graph, msgs, len(msgs))
	ctx = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
	rep = analyze(msgs, graph, ctx, len(msgs))
	assert rep.answers["F1"].total >= 1, "有「只改 X」约束就该有分母"
	assert rep.answers["F1"].yes == 0
	assert rep.answers["F2"].total == 1 and rep.answers["F2"].yes == 0, "有禁令、没违反 ⇒ 0/1 而不是 N/A"

	clean = [msg_user("改一下 auth"), msgs[1], msgs[2]]
	g2 = build_graph(clean, include_soft_edges=False)
	f2 = turn_facts(g2, clean, len(clean))
	ctx2 = {tf.turn: "\n".join(message_text(m) for m in clean[:tf.region_end]) for tf in f2}
	rep2 = analyze(clean, g2, ctx2, len(clean))
	assert rep2.answers["F2"].status == "not_applicable", "没提禁令 ⇒ 不给满分也不给 0，而是 N/A"


def test_f3_is_a_count_not_a_rate():
	from wsc._fixtures import msg_asst_use, msg_tool, msg_user

	msgs = [msg_user("看一下"),
	        msg_asst_use("u1", "Bash", {"command": "cat /root/secret"}),
	        msg_tool("u1", "Bash", "Access is denied", is_error=True),
	        msg_asst_use("u2", "Bash", {"command": "cat /etc/passwd"}),
	        msg_tool("u2", "Bash", "root:x:0:0")]
	graph = build_graph(msgs, include_soft_edges=False)
	facts = turn_facts(graph, msgs, len(msgs))
	ctx = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
	rep = analyze(msgs, graph, ctx, len(msgs))
	a = rep.answers["F3"]
	assert a.unit == "count" and a.rate is None
	assert a.yes == 1 and a.total == 2
	assert a.density_per_1k == 500.0


def test_artifact_answers_are_not_applicable_without_writes():
	from wsc._fixtures import msg_asst_use, msg_tool, msg_user

	readonly = [msg_user("看看代码"),
	            msg_asst_use("u1", "Read", {"path": "a.ts"}),
	            msg_tool("u1", "Read", "// a.ts")]
	graph = build_graph(readonly, include_soft_edges=False)
	facts = turn_facts(graph, readonly, len(readonly))
	ctx = {tf.turn: "\n".join(message_text(m) for m in readonly[:tf.region_end]) for tf in facts}
	rep = analyze(readonly, graph, ctx, len(readonly))
	for qid in ("A1", "A2", "A3"):
		assert rep.answers[qid].status == "not_applicable", f"{qid}: 无写操作 ⇒ N/A，不是失败"


def test_a4_is_external_truth_only():
	msgs = synth_session(turns=3, error_turn=1)
	graph = build_graph(msgs, include_soft_edges=False)
	facts = turn_facts(graph, msgs, len(msgs))
	ctx = {tf.turn: "\n".join(message_text(m) for m in msgs[:tf.region_end]) for tf in facts}
	a4 = analyze(msgs, graph, ctx, len(msgs)).answers["A4"]
	assert a4.status == "pending_sample" and a4.kind == "sample" and a4.total == 0
	assert a4.rate is None
	rec = aggregate({"s": {"A4": a4}})["A4"]
	assert rec["status"] == "not_applicable" and rec["gate_eligible"] is False
