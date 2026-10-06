"""A truncated primary task needs a published, executable recovery entrance."""
from dataclasses import replace

from synaptic.project import project
from synaptic.types import WscParams
from tests.wsc._recovery_contract import parse_read_refs
from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers


def test_long_primary_task_can_recover_its_actionable_tail(tmp_path):
    text = "Investigate the build records. " * 30 + "The release tag is R2026-10."
    params = replace(WscParams(), handle_style="read")
    view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
    projection = project([{"role": "user", "content": text}, {"role": "assistant", "content": "checking"}],
                         region_end=2, params=params, view_path=view)
    assert "R2026-10" not in projection.text
    entrances = parse_read_refs(projection.text)
    assert entrances, "stored original task has no published recovery entrance"
    entrance = entrances[0]
    retrieved = _strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view,
                                          offset=entrance.offset, limit=entrance.limit))
    assert retrieved == text
    assert "R2026-10" in retrieved


def test_short_multiline_primary_task_preserves_code_layout():
    text = "Inspect this fragment:\nif ready:\n    action()\nelse:\n    fallback()"
    projection = project([{"role": "user", "content": text}], region_end=1)
    assert text in projection.text


def test_primary_task_without_an_origin_is_not_silently_truncated():
    from synaptic.assemble import build_pins, render_pins
    from synaptic.seeds import Seeds

    text = "source-free goal " * 40 + "retain this last field"
    rendered = render_pins(build_pins(Seeds(original_task=text, goal=text)))[0][1]
    assert text in rendered
