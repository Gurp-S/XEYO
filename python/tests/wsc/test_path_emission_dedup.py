"""Path index entries are omitted only when final visible facts carry the full path."""
from synaptic.budget import apply_hot_budgets, segment_tokens
from synaptic.graph import build_graph
from synaptic.types import WscParams


def _budget(groups):
    return apply_hot_budgets(groups, WscParams(), graph=build_graph([]), region_end=0,
                            request_header="[REQUESTS]", request_skip=frozenset(), user_nodes=(),
                            fixed_headers=("[WORKING SET]", "[PATHS]", "[REQUESTS]"),
                            main_headers=("[MAIN]",), index_headers=())


def test_full_path_elsewhere_omits_only_the_duplicate_and_updates_audit():
    groups = {"[WORKING SET]": [("fs:src/a.py", "src/a.py | hash=123")],
              "[PATHS]": [("path:src/a.py", "a.py"), ("path:src/b.py", "b.py")]}
    output, audit = _budget(groups)
    assert output["[PATHS]"] == [("path:src/b.py", "b.py")]
    assert audit.fixed_tokens == sum(segment_tokens(items) for items in output.values())


def test_similar_path_or_only_basename_is_not_full_path_evidence():
    for line in ("src/a.py.old", "a.py", "/src/a.py", "src/a.py+backup"):
        output, audit = _budget({"[MAIN]": [("node:1", line)],
                                 "[PATHS]": [("path:src/a.py", "a.py")]})
        assert output["[PATHS]"] == [("path:src/a.py", "a.py")]


def test_exact_path_in_main_eliminates_an_empty_path_section():
    output, audit = _budget({"[MAIN]": [("node:1", 'Read({"path":"src/my file.py"})')],
                             "[PATHS]": [("path:src/my file.py", "my file.py")]})
    assert "[PATHS]" not in output
    assert audit.fixed_tokens == 0
