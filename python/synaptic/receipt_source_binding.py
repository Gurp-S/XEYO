"""Opt-in association of execution identity and immutable result read location."""
import os

from synaptic.coldstore import node_group_handle

ENV = "XEYO_WSC_RECEIPT_SOURCE_BINDING"


def record(receipt, handles):
    if os.environ.get(ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return receipt
    handle = node_group_handle((receipt["source"],))
    arguments = handles.read_arguments(handle)
    if arguments is None:
        return receipt
    return {**receipt, "result_source": {"tool": "Read", "arguments": arguments,
             "encoding": handles.encoding(handle), "view_lines": list(handles.span(handle))}}
