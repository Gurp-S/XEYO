from synaptic.assemble import render_decisions
from synaptic.prune import render_card_group
from synaptic.types import PruneCard
from synaptic.visible_paths import missing_paths


def test_group_path_already_in_conclusion_not_emitted_twice():
    card = PruneCard("c", "Read src/main.py 完成", files=("src/main.py", "src/other.py"), nodes=(1,))
    text = render_card_group([card])
    assert text.count("src/main.py") == 1
    assert "src/other.py" in text and "node://1" in text


def test_truncated_failure_conclusion_does_not_lose_first_path():
    card = PruneCard("c", "Bash 对 very/long/", files=("very/long/name.py",), error_sig="failed", nodes=(1,))
    text = render_decisions((card,))[0][1]
    assert "very/long/name.py" in text and "node://1" in text


def test_path_substrings_are_not_duplicates():
    paths = ("src/a.py", "a.py", "a.py", "a.py")
    for text in ("src/a.py.old", "/src/a.py", "a.py:stream", "prefix_a.py"):
        assert missing_paths(paths, text) == paths


def test_exact_spaced_and_unicode_paths():
    paths = ("src/my file.py", "源码/文件.py")
    assert missing_paths(paths, 'Read "src/my file.py"；源码/文件.py 完成') == ()


def test_filename_punctuation_does_not_make_a_partial_path_visible():
    for suffix in ("+backup", "@old", "$old", "%old", "=old", "&old", "!old", "#old", "~old", "[old]", "{old}", ",old", ";old"):
        assert missing_paths(("src/a.py",), "src/a.py" + suffix) == ("src/a.py",)


def test_group_keeps_all_conclusions_and_one_shared_recovery_handle():
    cards = [PruneCard("a", "Read src/a.py first", files=("src/a.py",), nodes=(1,)),
             PruneCard("b", "Read src/a.py second", files=("src/a.py",), nodes=(2,))]
    text = render_card_group(cards)
    assert all(c.conclusion in text for c in cards)
    assert "node://1,2" in text


def test_real_conclusion_truncation_preserves_full_failure_path_and_signature():
    from synaptic.graph import build_graph
    from synaptic.prune import _Unit, _conclusion

    path = "src/" + "long/" * 50 + "missing.py"
    signature = "FileNotFoundError: missing"
    unit = _Unit(0, (0,), "Read", False, signature, (path,), "")
    conclusion = _conclusion(build_graph([]), unit, 220)
    assert path not in conclusion and signature not in conclusion
    card = PruneCard("c", conclusion, files=(path,), error_sig=signature, nodes=unit.nodes)
    text = render_decisions((card,))[0][1]
    assert path in text and signature in text and "node://0" in text


def test_complete_error_signature_is_not_repeated():
    card = PruneCard("c", "Read 失败：FileNotFoundError: missing", error_sig="FileNotFoundError: missing")
    assert render_decisions((card,))[0][1].count(card.error_sig) == 1


def test_partially_truncated_signature_is_emitted_in_full():
    from synaptic.graph import build_graph
    from synaptic.prune import _Unit, _conclusion

    path = "src/" + "x" * 160 + ".py"
    signature = "PermissionError: required permission is missing for this operation"
    unit = _Unit(0, (0,), "Read", False, signature, (path,), "")
    conclusion = _conclusion(build_graph([]), unit, 220)
    assert path in conclusion and signature not in conclusion
    card = PruneCard("c", conclusion, files=(path,), error_sig=signature)
    text = render_decisions((card,))[0][1]
    assert signature in text and text.count(path) == 1
