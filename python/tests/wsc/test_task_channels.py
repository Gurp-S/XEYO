import json
from types import SimpleNamespace

from synaptic.task_channels import coalesce
from synaptic.types import Pin


def fixture(source=7, observed=True):
    records = [{"id": "verify", "status": "in_progress", "content": "验收详细定义"}]
    checkpoint = Pin("task_checkpoint", "任务状态", json.dumps({
        "observed": observed, "todo_source": source, "items": records}))
    seeds = SimpleNamespace(todo_observed=True, todo_source=7)
    pins = (Pin("todo:0", "TODO", "[in_progress] 验收详细定义"),
            Pin("unresolved:0", "失败记录", "actual failure", nodes=(5,)))
    return pins, checkpoint, seeds


def test_only_same_committed_task_labels_are_coalesced():
    pins, checkpoint, seeds = fixture()
    assert coalesce(pins, checkpoint, seeds) == pins[1:]
    assert pins[0].text == "[in_progress] 验收详细定义"


def test_different_source_or_unobserved_state_cannot_hide_facts():
    for source, observed in ((8, True), (7, False)):
        pins, checkpoint, seeds = fixture(source, observed)
        assert coalesce(pins, checkpoint, seeds) == pins
    pins, checkpoint, seeds = fixture()
    assert coalesce(pins, None, seeds) == pins
    different = (Pin("todo:0", "TODO", "different scope"), pins[1])
    assert coalesce(different, checkpoint, seeds) == different


def test_empty_committed_state_keeps_explicit_barrier():
    pins, checkpoint, seeds = fixture()
    barrier = (Pin("todo:0", "TODO", "observed active=0"),)
    empty = Pin("task_checkpoint", "任务状态", json.dumps({
        "observed": True, "todo_source": 7, "items": []}))
    assert coalesce(barrier, empty, seeds) == barrier
    seeds.todo_observed = False
    assert coalesce(pins, checkpoint, seeds) == pins


def test_real_projection_has_one_task_presentation_and_keeps_complete_fields(tmp_path):
    from tests.wsc.test_task_continuity import receipt, task
    from memory.wsc_projection import production_params
    from synaptic.project import project
    records = [task("verify", "in_progress", "验收详细定义\n逐项核对身份与输出")]
    rows = [{"role": "user", "id": "plan", "content": "当前任务的完整详细定义"}]
    rows += receipt("cp", records, {"objective": "当前任务", "context_message_ids": ["plan"]})
    output = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / "cold.txt")
    assert not any(pin.key.startswith("todo:") for pin in output.result.hot.pins)
    assert 'id="verify"' in output.text
    assert "逐项核对身份与输出" in output.text and '"output":"report.json"' in output.text
    assert "当前任务的完整详细定义" in output.text
    assert output.cold.texts[1] and output.cold.texts[2]
