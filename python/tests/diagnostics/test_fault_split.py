"""责任划分的验收：四类失败必须落到不同归属，且判"模型的错"要有送达证据。"""

from __future__ import annotations

import json

import pytest

from diagnostics.collect import ModelRequest, RunEvidence, ToolCall
from diagnostics.fault_split import (
	ENGINE,
	ENVIRONMENT,
	MIXED,
	MODEL,
	OUTCOME_FAIL,
	OUTCOME_LABEL,
	OUTCOME_NOT_ACCEPTED,
	OUTCOME_PASS,
	OUTCOME_SELF_REPORTED,
	UNDETERMINED,
	_tool_error_party,
	attribute_fault,
)
from diagnostics.identity import CONFIRMED_FAULT, SUSPECTED_CAUSE, EvidenceRef, Finding
from session.persistence import transcript_path


def _finding(rule_id: str, boundary: str, *, status: str = CONFIRMED_FAULT, detail: str = "") -> Finding:
	return Finding(
		rule_id=rule_id,
		rule_version=1,
		phenomenon=f"{rule_id} 现象",
		boundary=boundary,
		component="测试组件",
		status=status,
		evidence=[EvidenceRef(source="audit", locator="audit.jsonl", ref_id="L7", detail=detail)],
		coverage_gap="测试夹具",
		allowed_conclusion="测试夹具",
	)


def _run(**over) -> RunEvidence:
	base = dict(session_id="s1", turn_id="t1")
	base.update(over)
	return RunEvidence(**base)


def _write_transcript(session_id: str, rows: list[dict]) -> None:
	path = transcript_path(session_id)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# ---------- 四类失败：各归各方 ----------


def test_permission_block_is_engine_not_model() -> None:
	"""权限把调用挡下来：执行层事实，不能算模型没干活。"""
	run = _run()
	verdict = attribute_fault(run, [_finding("permission_block", "tool_permission", detail="tool_use_id=c1")])
	assert verdict["responsibility"] == ENGINE
	assert verdict["engine_confirmed"] >= 1
	assert "输入已不是任务本来的输入" in verdict["why"]


def test_tool_failure_with_missing_command_is_environment() -> None:
	"""命令不存在：外部世界的事实，引擎与模型都未被证明有错。"""
	run = _run()
	verdict = attribute_fault(run, [_finding("tool_failure", "tool_permission", detail="tool.finished is_error=true error_kind=COMMAND_NOT_FOUND")])
	assert verdict["responsibility"] == ENVIRONMENT


def test_engine_error_kind_inside_tool_failure_is_engine() -> None:
	run = _run()
	verdict = attribute_fault(run, [_finding("tool_failure", "tool_permission", detail="tool.finished is_error=true error_kind=PERMISSION_DENIED")])
	assert verdict["responsibility"] == ENGINE


def test_4xx_our_engine_fell_back_on_is_not_environment() -> None:
	"""引擎换通道重打的那次 4xx：被拒的是我方提交的形状，理由不可见 ⇒ 不判给外部世界。

	engine/query_loop.py 自己在 `_is_tool_pairing_400` 的注释里记着事故：无主 tool 结果
	造成的 400 曾被声道回退判据读成"厂商不接受声道"，"白打一次模型、并把失败记成
	protocol_fallback（误导归因）"。判据被证明会误判时，诊断层没资格替厂商定罪。
	"""
	run = _run()
	verdict = attribute_fault(
		run,
		[_finding(
			"provider_stream_failure",
			"model_request",
			detail="model.finished status=protocol_fallback error_code=HTTP_400 attempt=1",
		)],
	)
	assert verdict["responsibility"] != ENVIRONMENT
	assert verdict["environment_confirmed"] == 0
	assert any("降级" in s["fact"] and s["party"] == UNDETERMINED for s in verdict["chain"])


def test_rate_limited_request_stays_an_environment_fact() -> None:
	"""429 仍是外部世界的事实：拆这一刀不得把整条厂商通路都吸进"未定"。"""
	run = _run()
	verdict = attribute_fault(
		run,
		[_finding(
			"provider_stream_failure",
			"model_request",
			detail="llm.failure status=429 error_code=rate_limit attempt=1",
		)],
	)
	assert verdict["responsibility"] == ENVIRONMENT
	assert verdict["environment_confirmed"] == 1


def test_aborted_error_kind_is_not_blamed_on_the_model() -> None:
	"""ABORTED 由插件钩子 should_abort / 引擎"用户停止"分支写下，两者都不是模型侧。

	回归点直接钉在 _tool_error_party 上（它是本次修改的函数；attribute_fault 的顶层
	responsibility 只按 ENGINE/ENVIRONMENT 提升，不覆盖 MODEL 通路，测它会假绿）。
	ABORTED 曾在 _MODEL_KINDS 里 ⇒ 被归成"模型侧"，与当初 INTERNAL→ENGINE 同形。
	"""
	assert _tool_error_party("tool.finished is_error=true error_kind=ABORTED") == UNDETERMINED
	# 反面对照：确实该归模型的仍归模型，别把修复做成"全都不归因"。
	assert _tool_error_party("tool.finished is_error=true error_kind=INVALID_ARGUMENT") == MODEL


def test_transport_gap_is_engine_side_not_model() -> None:
	"""引擎已完成但界面没收到：责任在传输/显示边界，与模型无关。"""
	run = _run()
	verdict = attribute_fault(run, [_finding("wire_gap", "sse_gui", status=SUSPECTED_CAUSE)])
	# 疑似级传输缺口不足以定责
	assert verdict["responsibility"] == UNDETERMINED
	run2 = _run()
	verdict2 = attribute_fault(run2, [_finding("wire_gap", "sse_gui", status=CONFIRMED_FAULT)])
	assert verdict2["responsibility"] == ENGINE
	assert verdict2["transport_gap"] is True


# ---------- 判"模型的错"必须有送达证据 ----------


def test_model_fault_requires_constraint_shown(monkeypatch) -> None:
	constraint = "改完必须跑 pytest tests/diagnostics 才算完成"
	_write_transcript("s1", [
		{"id": "m1", "role": "user", "ts": 1.0, "content": constraint},
		{"id": "m2", "role": "assistant", "ts": 2.0, "content": "测试通过，任务已完成"},
	])
	sent = json.dumps([{"role": "user", "content": constraint}], ensure_ascii=False)

	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (sent, "working.json"))
	run = _run(
		pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "pins/p1.json"}],
		transcript_rows=[
			{"id": "m1", "role": "user", "content": constraint, "locator": "t.jsonl", "line_no": 1},
			{"id": "m2", "role": "assistant", "content": "测试通过，任务已完成", "locator": "t.jsonl", "line_no": 2},
		],
	)
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "shown"
	assert verdict["responsibility"] == MODEL
	assert verdict["task_outcome"] == OUTCOME_FAIL
	assert "self_report" in verdict


def test_unrecorded_commands_cannot_prove_the_action_was_skipped(monkeypatch) -> None:
	"""工具行的命令正文没落账：分不清"没跑测试"还是"没记命令"，不能判模型的错。

	真实审计里 tool.* 行不带 command / command_summary（入参摘要只写在 permission.*
	行上），所以"本轮 N 次调用里没有一项含 pytest"这件事永远没有依据。
	"""
	constraint = "改完必须跑 pytest 再说完成"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		transcript_rows=[
			{"id": "m1", "role": "user", "content": constraint, "locator": "t.jsonl", "line_no": 1},
			{"id": "m2", "role": "assistant", "content": "已完成，测试通过", "locator": "t.jsonl", "line_no": 2},
		],
		model_requests=[
			ModelRequest(model_request_id="r1", attempts=[{"attempt": 1, "kind": "model.finished", "status": "ok"}])
		],
		tool_calls=[ToolCall(tool_use_id="c1", tool_name="Read", started={"line_no": 3}, finished={"line_no": 4})],
	)
	verdict = attribute_fault(run, [])
	assert verdict["responsibility"] != MODEL
	assert not any("要求动作" in s["fact"] and s["party"] == "model" for s in verdict["chain"])
	assert any("命令" in s["fact"] and s["party"] == "undetermined" for s in verdict["chain"])


def test_unprovable_delivery_cannot_blame_the_model_for_a_skipped_action() -> None:
	"""命令有记录、动作确实没做，但"要求送没送到"证不出来：只报事实，不指责任何一方。

	真实数据里这条是有分母的：59 轮中唯一一条 ``required_action_skipped`` 恰好落在
	``shown_to_model=unprovable`` 的那 42 轮里——模型是否见过那句要求都无从证明。
	"""
	constraint = "改完必须跑 pytest 再说完成"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	run = _run(
		transcript_rows=[
			{"id": "m1", "role": "user", "content": constraint, "locator": "t.jsonl", "line_no": 1},
			{"id": "m2", "role": "assistant", "content": "已完成，测试通过", "locator": "t.jsonl", "line_no": 2},
		],
		model_requests=[
			ModelRequest(model_request_id="r1", attempts=[{"attempt": 1, "kind": "model.finished", "status": "ok"}])
		],
		tool_calls=[
			ToolCall(
				tool_use_id="c1",
				tool_name="Read",
				started={"line_no": 3, "command_summary": "read config"},
				finished={"line_no": 4, "command_summary": "read config"},
			)
		],
	)
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "unprovable"
	assert verdict["responsibility"] != MODEL
	assert any("要求动作" in s["fact"] for s in verdict["chain"]), "事实仍要说出来"
	assert not any(s["party"] == "model" for s in verdict["chain"])
	assert "required_action_skipped" not in [c["code"] for c in verdict["causes"]]


def test_missing_verifier_is_not_a_self_report_contradiction() -> None:
	"""没有验收记录时，自述不与任何东西矛盾：那句"验收记录显示…"是凭空指控。"""
	run = _run(
		transcript_rows=[
			{"id": "m1", "role": "user", "content": "改完跑一下测试", "locator": "t.jsonl", "line_no": 1},
			{"id": "m2", "role": "assistant", "content": "测试通过，任务已完成", "locator": "t.jsonl", "line_no": 2},
		],
	)
	verdict = attribute_fault(run, [])
	assert "self_report" not in verdict
	assert not any(s["party"] == "model" for s in verdict["chain"])
	# 但这句话必须被说出来：自述完成而无验收可核，是任务结局的一种，不是没有结局。
	assert verdict["task_outcome"] == OUTCOME_SELF_REPORTED
	assert verdict["task_outcome_label"] == OUTCOME_LABEL[OUTCOME_SELF_REPORTED]
	assert any(s["party"] == UNDETERMINED and "自述" in s["fact"] for s in verdict["chain"])


def test_post_hoc_pin_cannot_claim_context_loss_but_can_name_requirement(monkeypatch) -> None:
	"""两条判据分开：当场在场的原话才判"上下文丢了它"；事后声明只当要求来源。"""
	constraint = "改完必须跑 pytest"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	# 投影里带着该约束 ⇒ 不成立"引擎丢了约束"
	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		pins=[
			{"kind": "run_mark", "pin_id": "p0", "expected": constraint, "created_at": 999.0, "locator": "p0.json"},
			{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "p1.json"},
		],
		events=[_ev(1.0, "model.started"), _ev(2.0, "model.finished")],
	)
	verdict = attribute_fault(run, [])
	assert not any("源历史里存在，但不在最后发射的投影里" in s["fact"] for s in verdict["chain"])
	assert verdict["task_outcome"] == "accepted_fail"


def test_required_test_skipped_is_a_model_fault_without_a_verifier(monkeypatch) -> None:
	"""没有验收记录也能判：约束送达 + 要求跑测试 + 本轮没跑 + 没被挡 + 自述完成。"""
	constraint = "改完必须跑 pytest 再说完成"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		transcript_rows=[
			{"id": "m1", "role": "user", "content": constraint, "locator": "t.jsonl", "line_no": 1},
			{"id": "m2", "role": "assistant", "content": "已完成，测试通过", "locator": "t.jsonl", "line_no": 2},
		],
		model_requests=[ModelRequest(model_request_id="r1", attempts=[{"attempt": 1, "kind": "model.finished", "status": "ok"}])],
		tool_calls=[
			ToolCall(
				tool_use_id="c1",
				tool_name="Read",
				started={"line_no": 3},
				finished={"line_no": 4, "command_summary": "read config"},
			)
		],
	)
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "shown"
	assert verdict["responsibility"] == MODEL
	assert any("要求动作" in s["fact"] and s["party"] == "model" for s in verdict["chain"])


def test_blocked_action_is_not_a_model_fault(monkeypatch) -> None:
	"""同样要求跑测试，但被权限挡下：归引擎，不归模型。"""
	constraint = "改完必须跑 pytest 再说完成"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		permissions=[
			{"request_id": "apr1", "kind": "permission.resolved", "tool_name": "Bash", "approved": False, "outcome": "user_decided", "line_no": 9}
		],
	)
	verdict = attribute_fault(run, [])
	assert verdict["responsibility"] == ENGINE
	assert any(s["party"] == "engine" and "执行层" in s["fact"] for s in verdict["chain"])


def _ev(ts: float, kind: str):
	from diagnostics.identity import normalize_event

	return normalize_event(0, 1, {"ts": ts, "kind": kind, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1"})


def test_no_capture_and_no_projection_cannot_blame_model(monkeypatch) -> None:
	constraint = "改完必须跑测试"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: ("", ""))
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "pins/p1.json"}])
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "unprovable"
	assert verdict["responsibility"] == UNDETERMINED
	assert any("可复现记录" in m for m in verdict["missing_evidence"])


def test_constraint_not_sent_is_engine_loss(monkeypatch) -> None:
	constraint = "禁止改 gui/ 下的文件"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"role": "user", "content": "别的内容"}]), "working.json"))
	verdict = attribute_fault(_run(), [])
	assert verdict["shown_to_model"] == "not_shown"
	assert verdict["responsibility"] == ENGINE


def test_engine_and_model_both_holds_is_mixed(monkeypatch) -> None:
	constraint = "必须跑测试"
	_write_transcript("s1", [
		{"id": "m1", "role": "user", "ts": 1.0, "content": constraint},
		{"id": "m2", "role": "assistant", "ts": 2.0, "content": "测试通过"},
	])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(
		pins=[
			{"kind": "run_mark", "pin_id": "p0", "expected": constraint, "note": "结果不对", "locator": "pins/p0.json"},
			{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "pins/p1.json"},
		],
		transcript_rows=[
			{"id": "m2", "role": "assistant", "content": "测试通过", "locator": "t.jsonl", "line_no": 2},
		],
	)
	verdict = attribute_fault(run, [_finding("frozen_head", "wsc_fold")])
	assert verdict["responsibility"] == MIXED
	assert verdict["engine_confirmed"] >= 1


# ---------- 任务结局 ----------


def test_no_verifier_means_outcome_undetermined() -> None:
	verdict = attribute_fault(_run(), [])
	assert verdict["task_outcome"] == OUTCOME_NOT_ACCEPTED
	assert "无法判定" in verdict["task_outcome_label"]
	assert any("verifier" in m for m in verdict["missing_evidence"])


def test_bare_acceptance_failure_does_not_blame_model(monkeypatch) -> None:
	"""验收失败单独一条不够判模型：本轮开始前的红测长得一样。"""
	constraint = "改完必须跑 pytest 再说完成"
	_write_transcript("s1", [{"id": "m1", "role": "user", "ts": 1.0, "content": constraint}])
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (json.dumps([{"content": constraint}]), "w.json"))
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 1, "locator": "p1.json"}])
	verdict = attribute_fault(run, [])
	assert verdict["shown_to_model"] == "shown"
	assert verdict["task_outcome"] == "accepted_fail"
	assert verdict["responsibility"] == UNDETERMINED
	assert any("先于本轮存在" in m for m in verdict["missing_evidence"])
	# 原因照实列出：责任未定不等于原因没有
	assert "acceptance_failed" in [c["code"] for c in verdict["causes"]]


def test_green_verifier_does_not_become_model_fault() -> None:
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 0, "locator": "pins/p1.json"}])
	verdict = attribute_fault(run, [])
	assert verdict["task_outcome"] == OUTCOME_PASS
	assert verdict["responsibility"] == UNDETERMINED


def test_verifier_exit_above_128_is_verifier_error() -> None:
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": 137, "locator": "pins/p1.json"}])
	assert attribute_fault(run, [])["task_outcome"] == "verifier_error"


def test_missing_exit_code_is_not_treated_as_zero() -> None:
	run = _run(pins=[{"kind": "verifier", "pin_id": "p1", "name": "pytest", "exit_code": None, "locator": "pins/p1.json"}])
	verdict = attribute_fault(run, [])
	assert verdict["task_outcome"] == OUTCOME_NOT_ACCEPTED


# ---------- 纪律 ----------


def test_verdict_always_states_what_it_does_not_claim() -> None:
	verdict = attribute_fault(_run(), [])
	assert verdict["not_claimed"]
	assert any("概率" in s for s in verdict["not_claimed"])
	for step in verdict["chain"]:
		assert step["evidence"], "因果链上每一步都必须能回到原始记录"
		assert step["party"] in {ENGINE, MODEL, ENVIRONMENT, UNDETERMINED}


def test_report_and_markdown_carry_the_verdict(collect) -> None:
	from diagnostics.report import build_report, to_markdown

	run = collect([
		{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
		{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok"},
	])
	doc = build_report(run)
	assert doc["fault"]["responsibility"] in {ENGINE, MODEL, ENVIRONMENT, MIXED, UNDETERMINED}
	md = to_markdown(doc)
	assert "## 责任划分" in md
	assert "本报告不宣称" in md


def test_every_taxonomy_error_kind_has_an_explicit_party_decision() -> None:
	"""执行层新增一个 error_kind，就必须当场决定归谁，不许静默滑进"未定"。

	归属只由 fault_split 的三张表决定；没列进去的取值一律 UNDETERMINED。那是安全的下限，
	但同时是一次没人批准的弃权——INTERNAL 与 ABORTED 就是两次**有意**的弃权，
	在这里当例外登记；第三个没登记的名字出现时，这条应当红。
	"""
	import tools.error_taxonomy as taxonomy

	from diagnostics.fault_split import _ENGINE_KINDS, _ENVIRONMENT_KINDS, _MODEL_KINDS

	kinds = {v for k, v in vars(taxonomy).items() if k.isupper() and isinstance(v, str)}
	assert kinds, "扫描口径失效：分类表一个常量都没读到"
	unclaimed = kinds - _ENGINE_KINDS - _ENVIRONMENT_KINDS - _MODEL_KINDS
	assert unclaimed == {"INTERNAL", "ABORTED"}, (
		"这些 error_kind 没有归属决定，会被静默判成未定（要么进三张表，要么把弃权理由写进本用例）："
		f"{sorted(unclaimed ^ ({'INTERNAL'} | {'ABORTED'}))}"
	)


def _ev_with(ts: float, kind: str, **row) -> object:
	from diagnostics.identity import normalize_event

	return normalize_event(0, 1, {"ts": ts, "kind": kind, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", **row})


def test_session_scope_attribution_prose_follows_the_scope() -> None:
	"""会话级归因不许说「本轮」；按轮问诊时，同一批句子要说「本轮」。

	这些句子来自义务识别、送达判定与动作核对三条通路。报告端点接受空 turn_id，
	那时每条规则读的都是整个会话的行 —— 把会话级范围说成"本轮"就是替读者把范围缩窄了。
	"""

	def verdict_for(turn_id: str) -> dict:
		# 约束正文由 _last_user_obligation 从转录文件里取（与采集层的窗口无关），
		# 所以这条门要写真文件，不能只填 run.transcript_rows —— 那样它永远不会走到
		# 带「本轮」的那些句子上，门就成了空转。
		_write_transcript(
			"s1",
			[
				{"id": "m1", "role": "user", "ts": 0.5, "content": "改完必须跑 pytest 再说完成"},
				{"id": "m2", "role": "assistant", "ts": 2.0, "content": "已完成，测试通过"},
			],
		)
		run = _run(
			turn_id=turn_id,
			events=[
				_ev_with(1.0, "model.started", projection_id="pA_used"),
				_ev_with(1.2, "model.finished", projection_id="pA_used", status="ok"),
			],
			projections=[{"projection_id": "pB_retained", "created_at": 99.0, "locator": "w.json"}],
			transcript_rows=[
				{"id": "m1", "role": "user", "ts": 0.5, "content": "改完必须跑 pytest", "line_no": 1, "locator": "s1.jsonl", "in_run": True},
				{"id": "m2", "role": "assistant", "ts": 2.0, "content": "已完成，测试通过", "line_no": 2, "locator": "s1.jsonl", "in_run": True},
			],
		)
		return attribute_fault(run, [])

	def tripped(turn_id: str) -> list[str]:
		node = verdict_for(turn_id)

		def walk(value, path="fault"):
			if isinstance(value, str):
				if "本轮" in value or "这一轮" in value:
					yield path
			elif isinstance(value, dict):
				for k, v in value.items():
					yield from walk(v, f"{path}.{k}")
			elif isinstance(value, (list, tuple)):
				for i, v in enumerate(value):
					yield from walk(v, f"{path}[{i}]")

		return sorted(set(walk(node)))

	assert tripped("t1"), "轮次范围下没有任何句子说「本轮」——样本没跑到那些分支，这条门是空的"
	assert tripped("") == [], f"会话级归因里仍有「本轮」：{tripped('')}"


def test_unprovable_note_names_both_projections() -> None:
	""""证不出来"必须说清是哪块证据不在场：本轮用哪个投影、留存的是哪个。

	笼统的"无法判断"读起来像引擎状态不明；把两个标识摆出来，这条就成了可以拿审计行
	核对的话，也指明了要补的是按轮留存（capture），不是再去猜。
	"""
	from diagnostics.fault_split import _shown_to_model

	run = _run(
		events=[_ev_with(1.0, "model.started", projection_id="pA_used_this_turn"), _ev_with(2.0, "model.finished", projection_id="pA_used_this_turn")],
		projections=[{"projection_id": "pB_retained_last", "created_at": 99.0, "locator": "w.json"}],
	)
	out = _shown_to_model(run, "改完必须跑 pytest")
	assert out["state"] == "unprovable"
	assert "pA_used_" in out["note"] and "pB_retain" in out["note"], out["note"]
	assert "只留整会话最后一份" in out["note"]


def test_unprovable_note_without_any_projection_identity() -> None:
	"""两个标识都没有时不许编一个占位符上去：说"没带投影标识"就够了。"""
	from diagnostics.fault_split import _shown_to_model

	run = _run(events=[_ev_with(1.0, "model.started"), _ev_with(2.0, "model.finished")])
	out = _shown_to_model(run, "改完必须跑 pytest")
	assert out["state"] == "unprovable"
	assert "没有投影标识" in out["note"] or "没有留存的投影正文" in out["note"], out["note"]
	assert "pA" not in out["note"] and "None" not in out["note"]
