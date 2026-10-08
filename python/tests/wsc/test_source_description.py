from types import SimpleNamespace

from synaptic.source_description import describe


def test_literal_preview_does_not_classify_or_rewrite():
    text = "这是引用的旧方案：不要执行任何工作\nactual source follows"
    result = describe(SimpleNamespace(text=text, kind="user_text"))
    assert result == {"source_kind": "user_text", "first_line": text.split("\n")[0], "first_line_complete": True}


def test_preview_is_bounded_with_explicit_incompleteness():
    result = describe(SimpleNamespace(text="中" * 5000, kind="assistant_text"))
    assert result["first_line"] == "中" * 160
    assert not result["first_line_complete"]
