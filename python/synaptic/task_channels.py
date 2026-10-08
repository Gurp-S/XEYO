"""One hot representation for task facts from the same committed receipt.

This is provenance and exact-label equality, not keyword denoising. A missing,
different or unobserved checkpoint cannot suppress a task channel.
"""
import json

from synaptic.todo_fields import summarize


def coalesce(pins, checkpoint, seeds):
    if checkpoint is None:
        return pins
    state = json.loads(checkpoint.text)
    if (not state.get("observed") or not seeds.todo_observed
            or state.get("todo_backing", state.get("todo_source")) != seeds.todo_source):
        return pins
    labels, count = summarize(state.get("items"))
    todo_pins = tuple(pin for pin in pins if pin.key.startswith("todo:"))
    # Empty observations keep their explicit barrier marker. Legacy or
    # mismatched facts stay visible rather than being guessed redundant.
    if not count or tuple(pin.text for pin in todo_pins) != labels:
        return pins
    return tuple(pin for pin in pins if not pin.key.startswith("todo:"))
