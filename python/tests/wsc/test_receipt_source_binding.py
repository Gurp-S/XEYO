from copy import deepcopy

from synaptic.handles import HandleRenderer
from synaptic.receipt_source_binding import ENV, record


def test_binding_is_opt_in_and_never_mutates_receipt(monkeypatch):
    receipt = {"call_id": "a", "source": 2, "input": {"file_path": "current.txt"}, "result_inline": False}
    original = deepcopy(receipt)
    handles = HandleRenderer(style="read", path="cold.txt", node_ranges={"node://2": (3, 6)})
    monkeypatch.delenv(ENV, raising=False)
    assert record(receipt, handles) is receipt
    monkeypatch.setenv(ENV, "1")
    bound = record(receipt, handles)
    assert bound["result_source"] == {"tool": "Read", "arguments": {
        "file_path": "cold.txt", "offset": 3, "limit": 4}, "encoding": "original_lf", "view_lines": [3, 6]}
    assert receipt == original and {k: v for k, v in bound.items() if k != "result_source"} == original


def test_missing_read_location_does_not_invent_binding(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    receipt = {"call_id": "a", "source": 2}
    assert record(receipt, HandleRenderer()) is receipt
    handles = HandleRenderer(style="read", path="cold.txt", node_ranges={"node://1": (1, 2)})
    assert record(receipt, handles) is receipt


def test_binding_uses_emitted_page_not_full_span(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    handles = HandleRenderer(style="read", path="cold.txt", node_ranges={"node://2": (1, 80)},
                             line_lengths=tuple(2001 * index for index in range(81)))
    bound = record({"call_id": "a", "source": 2}, handles)["result_source"]
    assert bound["arguments"]["limit"] < 80
    assert bound["view_lines"] == [1, 80]
    assert handles.extract(handles.expression("node://2")) == ("node://2",)
