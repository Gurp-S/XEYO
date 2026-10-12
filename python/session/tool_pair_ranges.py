"""Identity spans across arrival order, independent of provider adjacency."""
from synaptic.textutil import tool_use_blocks, tool_result_blocks


def complete_ranges(messages):
    calls, results = {}, {}
    for index, row in enumerate(messages):
        for use in tool_use_blocks(row):
            uid = use.get('id')
            if isinstance(uid, (str, int)) and uid:
                calls.setdefault(uid, []).append(index)
        for result in tool_result_blocks(row):
            uid = result.get('tool_use_id')
            if isinstance(uid, (str, int)) and uid:
                results[uid] = index
    spans = []
    for uid, end in results.items():
        origins = [start for start in calls.get(uid, ()) if start < end]
        if origins:
            spans.append((min(origins), end + 1))
    return spans
