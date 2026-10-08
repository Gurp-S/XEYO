import json
from dataclasses import replace
from pathlib import Path

from evals.stale_goal_ab import tool_read
from evals.wsc_request_projection import arm
from evals.wsc_task_continuity_ab import task_event
from memory.wsc_projection import production_params
from synaptic.card_surface import ENV, PREFIX
from synaptic.coldstore import node_handle
from synaptic.project import project


def constrained_params():
    return replace(production_params(), main_segment_budget_tokens=100)


def fixture(checkpoint=True):
    rows = [{"role": "user", "id": "historical", "content": "顺口提一下旧任务"}]
    from evals.wsc_execution_behavior import event
    for index in range(18):
        rows += event(f"historical-{index}", "Bash", {"command": f"old_fixture_{index}"},
            {"content": "历史工作记录 " + "archive " * 1200, "is_error": False})
    rows += [{"role": "user", "id": "current", "content": "当前任务定义：核验退款零值，结果关联真实验证回执。"}]
    if checkpoint:
        rows += task_event("checkpoint", [{"id": "refund", "content": "核验退款零值", "status": "in_progress", "activeForm": "核验零值"}],
            {"objective": "核验退款零值", "context_message_ids": ["current"], "constraints": ["结果关联真实验证回执"]})
    return rows


def test_cards_become_readable_source_index_without_retiring_facts(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = fixture()
    with arm("1", tmp_path / "home"):
        baseline = project(rows, region_end=len(rows), params=constrained_params(), view_path=tmp_path / "old.txt")
        monkeypatch.setenv(ENV, "1")
        indexed = project(rows, region_end=len(rows), params=constrained_params(), view_path=tmp_path / "new.txt")
        assert indexed.result.hot.cards and baseline.result.hot.cards
        assert 'id="refund"' in indexed.text and "结果关联真实验证回执" in indexed.text
        assert "历史折叠来源索引" in indexed.text
        handle = next(handle for handle in indexed.cold.snapshots if handle.startswith(PREFIX))
        _, ranges = indexed.cold.render_text_view()
        first, last = ranges[handle]
        receipt = tool_read({"file_path": indexed.view_path, "offset": first, "limit": last-first+1}, tmp_path)
        assert not receipt["is_error"] and '"format":"card_source_index"' in receipt["content"]
        records = [json.loads(line) for line in indexed.cold.snapshots[handle].splitlines()]
        sources = {index for card in indexed.result.hot.cards for index in card.nodes}
        assert {record["source"] for record in records if "source" in record} == sources
        for record in records:
            if "view_lines" in record:
                assert tuple(record["view_lines"]) == ranges[node_handle(record["source"])]
        assert indexed.cold.texts == baseline.cold.texts
        # An index does not expose archived conclusions as current decisions.
        assert "[DECISIONS]" not in indexed.text
        assert len(indexed.text) < len(baseline.text)
        original = Path(indexed.view_path).read_bytes()
        project(rows + [{"role": "user", "content": "进度如何"}], region_end=len(rows)+1,
            params=constrained_params(), view_path=tmp_path / "next.txt", prev=indexed.state, cold=indexed.cold)
        assert Path(indexed.view_path).read_bytes() == original


def test_no_task_declaration_preserves_existing_card_surface(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setenv(ENV, "1")
    with arm("1", tmp_path / "home"):
        rows = fixture(checkpoint=False)
        result = project(rows, region_end=len(rows), params=constrained_params(), view_path=tmp_path / "cold.txt")
        assert not any(handle.startswith(PREFIX) for handle in result.cold.snapshots)
        assert not any(pin.key == "card_archive" for pin in result.result.hot.pins)


def test_archive_index_is_not_original_body_coverage(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setenv(ENV, "1")
    with arm("1", tmp_path / "home"):
        rows = fixture()
        result = project(rows, region_end=len(rows), params=constrained_params(), view_path=tmp_path / "cold.txt")
        from synaptic.handles import HandleRenderer
        _, ranges = result.cold.render_text_view()
        renderer = HandleRenderer(style="read", path=Path(result.view_path).as_posix(), node_ranges=ranges,
            handle_nodes=result.cold.handles)
        handle = next(handle for handle in result.cold.snapshots if handle.startswith(PREFIX))
        assert not renderer.extract_nodes(renderer.expression(handle))
        assert not renderer.recoverable_nodes(renderer.expression(handle))
