"""Deterministic handoff presentation of committed task facts.

The machine state remains authoritative. This renderer adds no plans, semantic
retirement, success inference, or model calls.
"""
import json

from synaptic.coldstore import node_group_handle


def scalar(value):
    # Keep each record's boundaries, including literal newlines and delimiters.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render(state, nodes, handles):
    lines = [f"任务交接快照：已提交清单回执 #{state['todo_source']}",
             "目标（声明）: " + (scalar(state.get("declared_objective")) if state.get("declared_objective") else "未观察"),
             "上下文声明: " + ("已观察" if state.get("context_observed") else "未观察")]
    for status, heading in (("in_progress", "进行中（声明）"), ("pending", "待办（声明）"), ("completed", "已完成（声明）")):
        items = [item for item in state["items"] if item["status"] == status]
        lines.append(heading + f": {len(items)} 项")
        for item in items:
            lines.append("- id=" + scalar(item.get("id")) + " 内容=" + scalar(item["content"]))
            extra = {key: value for key, value in item.items() if key not in {"id", "content", "status"}}
            if extra:
                lines.append("  字段=" + scalar(extra))
    terminal = state.get("terminal_task")
    if terminal:
        lines.append("终态任务（已提交声明）: " + scalar({key: value for key, value in terminal.items()
            if key not in {"preceding_executions", "verification_receipts", "unknown_verification_sources"}}))
        lines.append("  终态来源=" + handles.expression(node_group_handle((terminal["commit_source"],))))
        lines.append("终态任务的检查点绑定验收（执行事实）: " + str(len(terminal.get("verification_receipts", []))) + " 项")
        for receipt in terminal.get("verification_receipts", []):
            lines.append("- " + scalar(receipt))
            lines.append("  来源=" + handles.expression(node_group_handle((receipt["source"],))))
        for unknown in terminal.get("unknown_verification_sources", []):
            lines.append("- 未知验收来源=" + scalar(unknown))
        executions = terminal.get("preceding_executions")
        if executions:
            lines.append("终态提交前的执行事实（时间范围，任务关联未声明）: " + str(executions["observed_count"]) + " 项")
            for receipt in executions["inline_or_indexed"]:
                lines.append("- " + scalar(receipt))
                lines.append("  来源=" + handles.expression(node_group_handle((receipt["source"],))))
    for key, title in (("declared_decisions", "决定（声明）"), ("declared_constraints", "任务约束（声明）")):
        lines.append(title + f": {len(state[key])} 项")
        lines.extend("- " + scalar(value) for value in state[key])
    lines.append("执行回执: " + str(len(state["verification_receipts"])) + " 项")
    for receipt in state["verification_receipts"]:
        lines.append("- " + scalar(receipt))
        lines.append("  来源=" + handles.expression(node_group_handle((receipt["source"],))))
    executions = state.get("subsequent_executions")
    if executions:
        lines.append("检查点之后的执行事实（任务关联未声明）: " + str(executions["observed_count"]) + " 项")
        lines.append("当前显示范围: " + str(len(executions["inline_or_indexed"])) + " 项")
        for receipt in executions["inline_or_indexed"]:
            lines.append("- " + scalar(receipt))
            lines.append("  来源=" + handles.expression(node_group_handle((receipt["source"],))))
    lines.append("关联原文: " + str(len(state["context_sources"])) + " 项")
    for source in state["context_sources"]:
        lines.append("- message_id=" + scalar(source["message_id"]) + " source=#" + str(source["source"]))
        lines.append("  原文:")
        lines.extend("    " + line for line in source["text"].split("\n"))
        lines.append("  来源=" + handles.expression(node_group_handle((source["source"],))))
    for source in state.get("committed_fact_sources", []):
        lines.append("结构化声明来源: " + scalar(source))
        for index in dict.fromkeys(index for fact in source["facts"] for index in fact["sources"]):
            lines.append("  来源=" + handles.expression(node_group_handle((index,))))
    deferred = state.get("deferred_sources", [])
    if deferred:
        lines.append("关联原文（已定位，热层未内联）: " + str(len(deferred)) + " 项")
        for source in deferred:
            handle = node_group_handle((source["source"],))
            lines.append("- " + scalar({**source, "source_view_lines": handles.span(handle)}))
            lines.append("  来源编码=" + handles.encoding(handle))
            lines.append("  来源=" + handles.expression(handle))
    lines.append("未知来源: " + str(len(state["unknown_sources"])) + " 项")
    lines.extend("- " + scalar(item) for item in state["unknown_sources"])
    if state.get("checkpoint_source", -1) >= 0:
        lines.append("检查点声明回执=#" + str(state["checkpoint_source"]))
    lines.append("来源范围=" + handles.expression(node_group_handle(nodes)))
    return "\n".join(lines)
