from evals.wsc_real_report_continuation import archive_search
from evals.wsc_unfolded_source_ab import environment


def test_real_grep_locates_middle_archive_and_rejects_other_files(tmp_path):
    archive = tmp_path / ".xeyo_offload" / "wsc"
    archive.mkdir(parents=True)
    view = archive / "history.txt"
    content = "unrelated\n" * 210 + "Grep 匹配 137 个文件，limit=40\nnext_offset=40\n"
    view.write_text(content, encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("not an archive", encoding="utf-8")
    with environment(tmp_path):
        result = archive_search({"path": str(view), "pattern": "137", "output_mode": "content"}, tmp_path)
        assert not result["is_error"]
        assert "211:" in str(result["content"]) and "137" in str(result["content"])
        for path in (str(outside), str(archive), "../outside.txt"):
            denied = archive_search({"path": path, "pattern": "."}, tmp_path)
            assert denied["is_error"] and "Permission denied" in denied["content"]
    assert view.read_text(encoding="utf-8") == content


def test_real_grep_returns_exact_bound_section_with_authoritative_context(tmp_path):
    import json
    from synaptic.archive_passages import source_ranges
    from synaptic.coldstore import ColdStore
    archive = tmp_path / ".xeyo_offload" / "wsc"
    archive.mkdir(parents=True)
    view = archive / "history.txt"
    body = '# Reference\n## Acceptance\n137 items\nnext_offset40\n## Illustration\n173 items'
    cold = ColdStore()
    cold.put_nodes([(0, body, {})])
    cold.write_text_view(view)
    original = view.read_bytes()
    context = source_ranges(cold, [{"id": "original", "role": "user", "content": body}])
    with environment(tmp_path):
        result = archive_search({"path": str(view), "pattern": "next_offset", "output_mode": "content"},
                                tmp_path, {str(view.resolve()): context})
    data = json.loads(result['content'])
    assert not result['is_error']
    passage = data['source_passages'][0]
    assert passage['message_id'] == 'original' and passage['section_path'][-1]['title'] == 'Acceptance'
    assert '137 items' in passage['content'] and '173 items' not in passage['content']
    assert view.read_bytes() == original
