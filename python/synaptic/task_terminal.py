"""Bounded terminal declaration and preceding executions; never active scope."""
from synaptic.task_execution import collect


def project(snapshot, messages):
    terminal = snapshot.terminal
    if terminal is None:
        return None, ()
    sources = [terminal["checkpoint_source"], terminal["commit_source"]]
    state = dict(terminal)
    from synaptic.task_verification import collect as collect_verification
    receipts, unknown, verification_nodes = collect_verification(
        messages, terminal.get("verification_call_ids", []), terminal["commit_source"])
    state["verification_receipts"] = receipts
    state["unknown_verification_sources"] = unknown
    sources.extend(verification_nodes)
    if terminal["kind"] == "completed":
        # Evidence is frozen at the commit, not rewritten by later validation.
        executions, nodes = collect(messages[:terminal["commit_source"] + 1], terminal["checkpoint_source"])
        state["preceding_executions"] = executions
        sources.extend(nodes)
    return state, tuple(dict.fromkeys(index for index in sources if index >= 0))
