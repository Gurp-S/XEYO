"""AgentTool 包：受限于任务范围的短命子 Agent（见 agent_tool.py）。"""

from tools.agent_tool.agent_tool import AgentTool, AgentInput, SubagentOutput
from tools.agent_tool.prompt import DESCRIPTION, MULTI_AGENT_HINT, TOOL_NAME

__all__ = [
	"AgentTool",
	"AgentInput",
	"SubagentOutput",
	"DESCRIPTION",
	"MULTI_AGENT_HINT",
	"TOOL_NAME",
]
