import json

from evals.wsc_recall_executor import RecallExecutor
from tools.grep_tool.grep_tool import GrepTool


def test_native_match_at_long_line_tail_is_not_replaced_by_prefix(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    prefix = "长行🙂" * 15000
    target = "receipt_value=4827"
    (tmp_path / "a-8-.txt").write_text(prefix + target + "\n", encoding="utf-8")
    executor = RecallExecutor(tmp_path, "read_search")
    result = executor.execute("Grep", {"pattern": r"receipt_value=\d+", "path": "a-8-.txt", "output_mode": "matches"})
    assert not result["is_error"] and len(result["content"]) < 600
    record = json.loads(result["content"].splitlines()[0])
    assert record["text"] == target and record["line"] == 1
    assert record["byte_column"] == len(prefix.encode("utf-8")) + 1
    assert result["execution"]["grep_observation"]["kind"] == "match_excerpts"
    legacy = executor.execute("Grep", {"pattern": r"receipt_value=\d+", "path": "a-8-.txt", "output_mode": "content"})
    assert not legacy["is_error"] and target not in legacy["content"]


def test_match_record_pagination_is_not_line_pagination(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    (tmp_path / "a.txt").write_text("code=1 and code=2\ncode=3\n", encoding="utf-8")
    executor = RecallExecutor(tmp_path, "read_search")
    result = executor.execute("Grep", {"pattern": r"code=\d+", "path": "a.txt", "output_mode": "matches", "head_limit": 1, "offset": 1})
    assert not result["is_error"]
    record = json.loads(result["content"].splitlines()[0])
    assert record["text"] == "code=2" and record["line"] == 1 and record["byte_column"] == 12
    assert result["execution"]["grep_observation"] == {"kind": "match_excerpts", "returned_records": 1, "total_records": 3, "offset": 1}
    empty = executor.execute("Grep", {"pattern": r"code=\d+", "path": "a.txt", "output_mode": "matches", "offset": 3})
    assert not empty["is_error"] and "returned=0; total=3" in empty["content"]


def test_default_surface_unchanged_and_context_is_not_silently_discarded(monkeypatch, tmp_path):
    monkeypatch.delenv("XEYO_WSC_TASK_CONTINUITY", raising=False)
    modes = GrepTool(cwd=str(tmp_path)).schema()["input_schema"]["properties"]["output_mode"]["enum"]
    assert "matches" not in modes
    executor = RecallExecutor(tmp_path, "read_search")
    assert executor.execute("Grep", {"pattern": "x", "output_mode": "matches"})["is_error"]
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    result = executor.execute("Grep", {"pattern": "x", "output_mode": "matches", "context": 2})
    assert result["is_error"] and "matches_context_settings_unavailable" in result["content"]


def test_zero_width_pattern_does_not_fabricate_absence(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    (tmp_path / "a.txt").write_text("present\n", encoding="utf-8")
    result = RecallExecutor(tmp_path, "read_search").execute("Grep", {"pattern": "^", "path": "a.txt", "output_mode": "matches"})
    assert not result["is_error"] and "returned=0; total=0" in result["content"]
    assert "No matches found" not in result["content"]


def test_content_single_file_pagination_uses_numeric_source_lines(monkeypatch, tmp_path):
    (tmp_path / "a-8-.txt").write_text("\n".join(f"tag code={index}" for index in range(1, 13)), encoding="utf-8")
    executor = RecallExecutor(tmp_path, "read_search")
    query = {"pattern": "tag", "path": "a-8-.txt", "output_mode": "content", "head_limit": 1, "offset": 1}
    monkeypatch.delenv("XEYO_WSC_TASK_CONTINUITY", raising=False)
    old = executor.execute("Grep", query)
    assert not old["is_error"] and "code=10" in old["content"]
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    new = executor.execute("Grep", query)
    assert not new["is_error"] and "a-8-.txt:2:tag code=2" in new["content"]


def test_invalid_regex_keeps_native_failure_instead_of_position_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    (tmp_path / "a.txt").write_text("present\n", encoding="utf-8")
    result = RecallExecutor(tmp_path, "read_search").execute("Grep", {"pattern": "[", "path": "a.txt", "output_mode": "matches"})
    assert result["is_error"] and "regex" in result["content"]
    assert "match_positions_unavailable" not in result["content"]
