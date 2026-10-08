import hashlib
import json
import re
from pathlib import Path

from evals.stale_goal_ab import tool_read
from evals.wsc_request_projection import arm
from evals.wsc_task_continuity_ab import task_event
from memory.wsc_projection import production_params
from synaptic.coldstore import ColdStore, node_handle
from synaptic.chunked_recovery import prepare
from synaptic.read_plan import first_page_end, line_prefix
from synaptic.project import project


def fixture(plan):
    return [{"role": "user", "content": plan, "id": "large-plan"}] + task_event("commit",
        [{"id": "work", "content": "核验长文档定义", "status": "in_progress", "activeForm": "核验定义"}],
        {"objective": "核验长文档定义", "context_message_ids": ["large-plan"]})


def actual_read_records(path, start, end):
    lengths = line_prefix(path.read_text(encoding="utf-8"))
    rows, calls = [], 0
    while start <= end:
        stop = first_page_end(start, end, lengths)
        result = tool_read({"file_path": str(path), "offset": start, "limit": stop-start+1}, path.parent)
        assert not result["is_error"], result["content"]
        for line in result["content"].splitlines():
            matched = re.match(r"^\s*\d+→(.*)$", line)
            if matched:
                rows.append(json.loads(matched[1]))
        calls += 1
        start = stop + 1
    return rows, calls


def decode(records):
    restored, current, text = {}, None, ""
    for record in records:
        if record.get("format") == "json_chunks":
            if current is not None:
                assert len(text) == current["characters"]
                assert hashlib.sha256(text.encode()).hexdigest() == current["sha256"]
                restored[current["source"]] = text
            current, text = record, ""
        else:
            assert record["start"] == len(text)
            assert record["end"] - record["start"] == len(record["text"])
            text += record["text"]
    if current is not None:
        assert len(text) == current["characters"]
        assert hashlib.sha256(text.encode()).hexdigest() == current["sha256"]
        restored[current["source"]] = text
    return restored


def test_known_over_budget_source_is_deferred_with_its_own_read(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    plan = "x" * 35000 + "\nconstraint-code=7391"
    with arm("1", tmp_path / "home"):
        result = project(fixture(plan), region_end=3, params=production_params(), view_path=tmp_path / "cold.txt")
        state = json.loads(next(pin.text for pin in result.result.hot.pins if pin.key == "task_checkpoint"))
        assert not state["unknown_sources"] and not state["context_sources"]
        assert state["deferred_sources"][0]["source"] == 0
        assert state["deferred_sources"][0]["payload_bytes"] == len(plan.encode())
        assert "来源编码=original_lf" in result.text
        assert result.cold.texts[0] == plan


def test_atomic_long_source_and_complete_group_are_lossless_through_real_read(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    plan = ('quoted "\\\t' + "长文档" * 40000 + "\r\nfinal-code=7391")
    with arm("1", tmp_path / "home"):
        result = project(fixture(plan), region_end=3, params=production_params(), view_path=tmp_path / "cold.txt")
        from synaptic.chunked_recovery import PREFIX
        view = Path(result.view_path)
        _, ranges = result.cold.render_text_view()
        from synaptic.group_recovery import recovery_renderer
        from synaptic.coldstore import node_group_handle
        group = node_group_handle((0, 2))
        result.cold.bind(group, (0, 2))
        renderer = recovery_renderer(result.cold, view.as_posix(), ranges,
            line_prefix(view.read_text(encoding="utf-8")), prepare(result.cold))
        source_handle = node_handle(0)
        assert renderer.encoding(source_handle) == "json_chunks"
        assert 0 in renderer.recoverable_nodes(renderer.expression(source_handle))
        assert 0 not in renderer.extract_nodes(renderer.expression(source_handle))
        assert 0 in renderer.recoverable_nodes(result.text)
        original_start, original_end = ranges[node_handle(0)]
        unrecoverable = tool_read({"file_path": str(view), "offset": original_start,
            "limit": original_end-original_start+1}, view.parent)
        assert unrecoverable["is_error"]  # Original atomic view cannot be paged.
        singles = [handle for handle in result.cold.snapshots if handle.startswith(PREFIX)
                   and result.cold.handles[handle] == (0,)]
        assert singles and "来源编码=json_chunks" in result.text
        records, count = actual_read_records(view, *ranges[singles[0]])
        assert count >= 2 and decode(records) == {0: plan}
        assert not any(len(result.cold.handles[handle]) > 1 for handle in result.cold.snapshots if handle.startswith(PREFIX))
        expression = renderer.expression(group)
        assert renderer.recoverable_nodes(expression) >= {0, 2}
        assert 0 not in renderer.extract_nodes(expression)
        assert "source=#0" in expression and "source=#2" in expression
        old_bytes = view.read_bytes()
        project(fixture(plan) + [{"role": "user", "content": "later fact"}], region_end=4,
            params=production_params(), view_path=tmp_path / "next.txt", prev=result.state, cold=result.cold)
        assert view.read_bytes() == old_bytes


def test_chunk_copies_are_idempotent_in_main_flow(monkeypatch):
    cold = ColdStore()
    cold.put_nodes([(0, "x" * 120000, {})])
    monkeypatch.delenv("XEYO_WSC_TASK_CONTINUITY", raising=False)
    first = prepare(cold)
    assert node_handle(0) in first and cold.snapshots
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    first = prepare(cold)
    before = cold.to_json()
    assert prepare(cold) == first and cold.to_json() == before
    assert cold.texts[0] == "x" * 120000 and node_handle(0) in first


def test_real_paged_read_receipt_reports_selected_view_geometry(monkeypatch, tmp_path):
    from evals.wsc_execution_behavior import Executor, event
    from synaptic.receipt_render import render
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    (tmp_path / "page.txt").write_text("first\nsecond\nthird\n", encoding="utf-8")
    args = {"file_path": "page.txt", "offset": 2, "limit": 1}
    result = Executor(tmp_path).execute("Read", args)
    facts = result["execution"]["read_observation"]
    assert facts["returned_range"] == [2, 2] and facts["view_total_lines"] == 3
    emitted = render(event("native-page", "Read", args, result))
    header = emitted[-1]["content"][0]["content"].split("\n", 1)[0].split("=", 1)[1]
    assert json.loads(header)["read_observation"] == facts
