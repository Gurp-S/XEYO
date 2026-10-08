"""Both sides of denoising: remove display noise without hiding failure evidence."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from synaptic.graph import build_graph
from synaptic.seeds import collect_seeds
from synaptic.project import project
from synaptic.types import WscParams
from wsc._fixtures import msg_user, msg_asst_use, msg_tool


def failed(command="pytest tests/a.py", diagnostic="exit code 1", uid="b"):
    return [msg_user("执行测试"), msg_asst_use(uid, "Bash", {"command": command}),
            msg_tool(uid, "Bash", diagnostic, is_error=True)]


def test_authoritative_empty_is_empty_and_legacy_does_not_import_tail():
    rows = failed()
    graph = build_graph(rows)
    assert not collect_seeds(graph, rows, {}, region_end=3, unresolved_idx=frozenset()).unresolved_errors
    assert not collect_seeds(graph, rows, {}, region_end=1).unresolved_errors


@pytest.mark.parametrize("text", ["AssertionError: expected 42, got 41...",
                                  "FileNotFoundError: /project/config.json ...",
                                  "failed to compile src/main.rs..."])
def test_truncated_diagnostics_remain_evidence(text):
    from synaptic.textutil import is_useful_error_sig
    assert is_useful_error_sig(text)


def test_unfinished_command_declared_paths_survive_but_narrative_example_does_not(monkeypatch):
    from synaptic.path_origins import declared_paths
    graph = build_graph([msg_user("例子 example.py"), msg_asst_use("u", "Bash", {"command": "pytest tests/a.py tests/b.py"})])
    assert set(declared_paths(graph.node(1), graph)) == {"tests/a.py", "tests/b.py"}
    assert not declared_paths(graph.node(0), graph)


def test_retired_human_floor_does_not_reactivate_all_history(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_REQUIREMENT_FLOOR", "1")
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    text = "任务方案\n" + "不可省略的约束\n" * 180 + "工具 + 类别 + 目标"
    rows = [msg_user(text), {"role": "assistant", "content": "观察"}, msg_user("继续"), msg_user("还有第二批")]
    p = replace(WscParams(), hot_budget_tokens=80, fixed_segment_budget_tokens=40, main_segment_budget_tokens=40)
    output = project(rows, region_end=len(rows), params=p)
    assert text not in output.result.hot.text
    assert output.cold.texts[0] == text
    assert not any(pin.key == "goal" for pin in output.result.hot.pins)
    assert output.state.budget["request_mode"] != "verbatim_history"


def test_failure_facts_keep_zero_information_failure_and_exact_sources(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    monkeypatch.setenv("XEYO_WSC_USEFUL_SIG_GATE", "1")
    output = project(failed(), region_end=3)
    pin = next(p for p in output.result.hot.pins if p.key == "failure_archive")
    assert pin.nodes == (1, 2)
    assert output.seeds.unresolved_source_groups == ((2,),)
    assert "Bash reported_failure target=tests/a.py" in output.seeds.unresolved_errors[0]


def test_identity_grouping_preserves_all_occurrences_and_separates_commands(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = failed(uid="a") + failed(uid="b") + failed("cat tests/a.py", uid="c")
    output = project(rows, region_end=len(rows))
    assert output.seeds.unresolved_source_groups == ((2, 5), (8,))
    assert next(p for p in output.result.hot.pins if p.key == "failure_archive").nodes == (1, 2, 4, 5, 7, 8)


def test_unknown_scopes_do_not_merge_even_with_identical_diagnostics(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = [msg_user("查看"), msg_tool("a", "Read", "failed", is_error=True), msg_tool("b", "Read", "failed", is_error=True)]
    output = project(rows, region_end=3)
    assert output.seeds.unresolved_source_groups == ((1,), (2,))
    assert next(p for p in output.result.hot.pins if p.key == "failure_archive").nodes == (1, 2)


@pytest.mark.parametrize("tokens", [0, 47999, 48000, 70000])
def test_first_fold_admission_no_longer_reads_the_removed_watermark(monkeypatch, tokens):
    """``XEYO_WSC_SOFT_WATERMARK`` 退场（2026-10-08 用户裁定）后的首次折叠准入契约。

    原契约：低于配置水位拒绝首次普通折叠。退场后绝对水位不得放行自动折叠
    （见 ``memory/wsc_timing`` 的判据），该门读到的水位恒 0 ⇒ 恒放行；自动折叠的
    唯一依据改由容量压力（≥ 声明容量的 85%）给。设了环境变量也不再生效。
    """
    from memory.wsc_first_admission import admit

    monkeypatch.setenv("XEYO_WSC_SOFT_WATERMARK", "48000")   # 已退场：设了不生效
    account = {}
    assert admit(SimpleNamespace(last_prompt_tokens=tokens), account) is True
    assert account["first_soft_watermark"] == 0, account      # 水位恒 0（退场后）


def test_completed_snapshot_is_absorbed_without_redundant_event(monkeypatch, tmp_path):
    from memory.wsc_goal_events import augment
    from unittest.mock import patch
    monkeypatch.setenv("XEYO_WSC_REQUEST_PROJECTION", "1")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    raw = [msg_user("查看现状")]
    with patch("memory.wsc_goal_source.snapshot", return_value={"goal_id":"g", "revision":4, "status":"completed", "text":"旧目标"}):
        actual, _ = augment(raw, 1, 1, head="new", cwd=str(tmp_path), session="s", source_layout="v1",
                            lifecycle={"goal_id":"g", "revision":4, "status":"completed", "goal":""})
    assert actual == raw


@pytest.mark.parametrize("prose", ["all passed", "AssertionError: quoted example...", "Permission denied: illustrative", "", "random" * 900])
def test_typed_receipt_identity_and_presence_are_independent_of_result_prose(monkeypatch, prose):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = failed(diagnostic=prose)
    rows[-1]["content"][0].update(is_error=False, execution={"status":"error", "complete":True})
    output = project(rows, region_end=3)
    assert next(p for p in output.result.hot.pins if p.key == "failure_archive").nodes == (1, 2)
    assert "Bash error target=tests/a.py" in output.seeds.unresolved_errors[0]


def test_typed_success_quoting_failures_does_not_become_unresolved(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = failed(diagnostic="FAILED other.py::test_x\n10 failed, 20 passed")
    rows[-1]["content"][0].update(is_error=False, execution={"status":"ok", "complete":True})
    output = project(rows, region_end=3)
    assert not output.seeds.unresolved_errors


def test_first_normal_fold_via_runtime_stays_put_after_watermark_retirement(monkeypatch, mem_switch):
    """水位旋钮退场后：首次普通折叠不再由绝对水位放行 ⇒ 该门短路，cursor 保持不动。"""
    from wsc.test_fold_gate_coverage import _press, _big_msgs
    monkeypatch.setenv("XEYO_WSC_SOFT_WATERMARK", "48000")   # 已退场：设了不生效
    assert _press(monkeypatch, mem_switch, msgs=_big_msgs(40), cursor=0).compact_cursor == 0


def test_goal_lifecycle_runs_through_real_adapter_and_real_store(monkeypatch, tmp_path):
    from evals.wsc_goal_event_replay import evaluate
    rows = [msg_user("当前观察")] + [{"role":"assistant", "content":f"观察 {i}\n" + "x" * 1500} for i in range(68)]
    result = evaluate(rows, tmp_path)
    assert all(result["acceptance"].values())


def test_user_literal_tags_are_not_deleted_as_machine_noise(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    text = "<system-reminder>这是用户给的测试样例，不是引擎注入</system-reminder>"
    rows = [msg_user(text)]
    assert text in project(rows, region_end=1).text


def test_typed_denial_is_constraint_with_all_sources_and_target_identity(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = failed(uid="a") + failed(uid="b") + failed("pytest tests/b.py", uid="c")
    for i in (2, 5, 8):
        rows[i]["content"][0]["execution"] = {"status":"error", "error_kind":"PERMISSION_DENIED", "complete":True}
    output = project(rows, region_end=len(rows))
    pins = [pin for pin in output.result.hot.pins if pin.key.startswith("denial:")]
    assert [p.nodes for p in pins] == [(2, 5), (8,)]
    assert not output.seeds.unresolved_errors


def test_multiple_failures_without_single_invocation_are_not_falsely_merged(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = [msg_user("同时验证")]
    for i in range(2):
        rows.append({"role":"assistant", "content":[
            {"type":"tool_use", "id":f"a{i}", "name":"Bash", "input":{"command":"pytest tests/a.py"}},
            {"type":"tool_use", "id":f"b{i}", "name":"Bash", "input":{"command":"pytest tests/b.py"}}]})
        rows.append({"role":"user", "content":[
            {"type":"tool_result", "tool_use_id":f"a{i}", "content":"failed", "is_error":True},
            {"type":"tool_result", "tool_use_id":f"b{i}", "content":"failed", "is_error":True}]})
    output = project(rows, region_end=5)
    assert output.seeds.unresolved_source_groups == ((2,), (4,))


def test_path_candidate_origin_does_not_claim_filesystem_existence(monkeypatch):
    from synaptic.path_origins import origin
    graph = build_graph([msg_asst_use("a", "Read", {"file_path":"missing.py"}),
                         msg_asst_use("b", "Bash", {"command":"pytest tests/b.py"})])
    assert origin(graph, "missing.py", 2) == "tool_argument"
    assert origin(graph, "tests/b.py", 2) == "command_mention"


def test_legacy_signature_gate_can_only_hide_excerpt_not_failure_or_origin(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_USEFUL_SIG_GATE", "1")
    rows = failed(diagnostic="exit code 1")
    output = project(rows, region_end=3)
    pins = [p for p in output.result.hot.pins if p.key.startswith("unresolved:")]
    assert not pins
    archive = next(p for p in output.result.hot.pins if p.key == "failure_archive")
    assert archive.nodes == (1, 2)
    assert "executions=1 identities=1 coverage=unknown" in output.text
    assert "exit code 1" in output.cold.texts[2]


def test_lifecycle_uses_stable_invocation_identity_across_diagnostic_changes(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    first = project(failed(uid="a"), region_end=3)
    rows = failed(uid="a") + failed(uid="b", diagnostic="ValueError: a different diagnostic")[1:]
    second = project(rows, region_end=5)
    assert first.state.lifecycle["unresolved"] == second.state.lifecycle["unresolved"]
    assert second.state.lifecycle["failure_identity_schema"] == "invocation-v1"


def test_conflicting_call_id_is_unknown_instead_of_assigned_to_last_input(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = failed("pytest tests/a.py", uid="same") + failed("pytest tests/b.py", uid="same")[1:]
    output = project(rows, region_end=5)
    assert output.graph.use_signatures["same"] == ""
    assert output.seeds.unresolved_source_groups == ((2,), (4,))
    assert all("target=unknown" in text for text in output.seeds.unresolved_errors)


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "Bash", "Write", "UnknownTool"])
def test_explicit_machine_failure_survives_empty_body_for_every_tool(monkeypatch, tool):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = [msg_user("检查"), msg_asst_use("call", tool, {"file_path":"tests/a.py"}),
            msg_tool("call", tool, "", is_error=True)]
    output = project(rows, region_end=3)
    assert output.graph.node(2).is_error
    assert output.seeds.unresolved_source_groups == ((2,),)


def test_conflicting_success_status_cannot_erase_explicit_failure(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_FAILURE_FACTS", "1")
    rows = failed(diagnostic="")
    rows[-1]["content"][0]["execution"] = {"status":"ok", "complete":True}
    output = project(rows, region_end=3)
    assert output.seeds.unresolved_source_groups == ((2,),)
    assert "verdict_conflict" in output.seeds.unresolved_errors[0]
