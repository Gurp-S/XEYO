from evals.wsc_recall_executor import RecallExecutor


def test_recall_surface_cannot_execute_mutations_or_escape_root(tmp_path):
    executor = RecallExecutor(tmp_path, "read_search")
    assert {tool["name"] for tool in executor.schemas()} == {"Read", "Grep"}
    assert executor.execute("Write", {"file_path": "result.txt", "content": "x"})["is_error"]
    assert not (tmp_path / "result.txt").exists()
    assert executor.execute("Read", {"file_path": "../outside.txt"})["is_error"]
    assert executor.execute("Grep", {"pattern": "x", "path": ".."})["is_error"]


def test_recall_search_is_product_tool_and_single_line_excerpt_can_be_read(tmp_path):
    (tmp_path / "source.txt").write_text("start\nrequest_code=7391\nend\n", encoding="utf-8")
    executor = RecallExecutor(tmp_path, "read_search")
    result = executor.execute("Grep", {"pattern": "request_code", "path": "source.txt", "output_mode": "content"})
    assert not result["is_error"] and "request_code=7391" in result["content"]
    result = executor.execute("Read", {"file_path": "source.txt", "offset": 2, "limit": 1})
    assert not result["is_error"] and "request_code=7391" in result["content"]
