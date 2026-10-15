"""Workflow 工具文案。事实型描述：只说能做什么、参数是什么，不给编排建议。"""

WORKFLOW_TOOL_NAME = "Workflow"

DESCRIPTION = (
    "Runs a model-written orchestration script that starts sub-agents. "
    "The script is plain Python restricted to: agent(prompt, label=, schema=, "
    "scope=, tools=, agent_type=), parallel([callables]), pipeline(items, *stages), "
    "phase(title), log(message), plus len/range/enumerate/zip/sorted/min/max/sum/"
    "str/int/float/bool/list/dict/set/tuple/abs/round/any/all/to_json/from_json. "
    "No import, no attribute access, no file/network access. "
    "agent() returns the child's final text, or a dict when schema is given, "
    "or None when the child failed. args and meta are available as globals. "
    "The result body is the script's return value."
)

SHORT_DESCRIPTION = (
    "Runs a restricted Python orchestration script that starts sub-agents "
    "(agent/parallel/pipeline). No imports; returns the script's value."
)
