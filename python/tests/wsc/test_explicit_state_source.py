from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from evals.wsc_append_state import install_note_exclusion
from synaptic.project import project
from synaptic.types import WscParams
from tests.wsc._fixtures import synth_session


def rows():
    messages = synth_session(turns=10)
    messages.insert(1, {"role": "user", "content": "Keep obsolete marker STATE_PATH_OLD src/old.py",
                        "note_key": "world_state", "note_fp": "old"})
    messages.append({"role": "user", "content": "Current marker STATE_PATH_NEW src/new.py",
                     "note_key": "world_state", "note_fp": "new"})
    return messages


def signature(result):
    return (result.text, result.cold.texts, result.seeds, result.graph.file_index,
            result.graph.nodes, result.audit, result.denoise)


def test_explicit_option_matches_retained_shadow_hook_and_default_is_unchanged():
    messages = rows()
    params = replace(WscParams(), journal_layout=False, freeze_main_chain=False)
    default = project(messages, region_end=len(messages), params=params)
    assert signature(default) == signature(project(messages, region_end=len(messages), params=params,
                                                   exclude_state_notes=False))
    with install_note_exclusion():
        expected = project(messages, region_end=len(messages), params=params)
    actual = project(messages, region_end=len(messages), params=params, exclude_state_notes=True)
    assert signature(actual) == signature(expected)
    assert actual.cold.texts[1] == messages[1]["content"]
    assert "STATE_PATH_OLD" not in actual.text and "STATE_PATH_NEW" not in actual.text


def test_interleaved_concurrent_calls_keep_independent_source_semantics():
    messages = rows()
    params = replace(WscParams(), journal_layout=False, freeze_main_chain=False)
    def run(enabled):
        return signature(project(messages, region_end=len(messages), params=params,
                                 exclude_state_notes=enabled))
    expected = {enabled: run(enabled) for enabled in (False, True)}
    assert expected[False] != expected[True]
    options = [False, True] * 12
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, options))
    assert all(value == expected[enabled] for enabled, value in zip(options, results))
