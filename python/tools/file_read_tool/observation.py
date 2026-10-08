"""Read view kind from the producer, independent of returned prose."""
from synaptic.task_checkpoint import enabled


def attach(result, output):
    if enabled():
        observation = {"kind": output.type}
        if output.type == "text" and not output.symbol_meta:
            count = output.content.count("\n") + (1 if output.content else 0)
            if getattr(output, "structured", False):
                # 这次给的是结构而不是正文：如实标注，且 returned_range 置空——
                # 结构文本的行数不是文件行号，报 [1, 43] 会被读成"读了前 43 行"。
                observation["view"] = "structure"
                observation.update(
                    view_total_lines=output.total_lines, returned_range=None
                )
            else:
                observation.update(view_total_lines=output.total_lines,
                    returned_range=[output.start_line, output.start_line + count - 1] if count else None)
        result.metadata = {**(result.metadata or {}), "read_observation": observation}
    return result
