"""Agent tool description (when to spawn a sub-agent)."""

TOOL_NAME = "Agent"

DESCRIPTION = (
	"Spawn a short-lived scoped sub-agent (task-style isolation). "
	"Always available in Agent mode — Multi-Agent chip only soft-prefers spawn.\n"
	"Use when work benefits from isolation or parallelism: multi-file explore/edit, "
	"independent docs/dirs, research that would bloat the main transcript. "
	"You may call Agent multiple times in ONE turn for independent scopes "
	"(they run concurrently).\n"
	"Provide task_id, desc; optional scope (write paths this worker may touch; "
	"empty scope = read-only hard gate, no Write/Edit), required_tools "
	"(Read, Edit, Grep, Glob…), and reuse_agent_id to retry an existing sidechain.\n"
	"Do NOT spawn for simple Q&A or a single-file edit you can do yourself. "
	"Sub-agents get Git + a readonly Bash sandbox (allowlist only; else DENY, no ASK); "
	"they cannot use Memory or spawn Agents. "
	"After tool_result(s), YOU write the final answer to the user."
)

# Composer Multi-Agent chip：挂到本轮 T_now。E2 裁决：只告知事实
# （用户开启了 multi-agent），不教模型怎么拆活——拆不拆、何时派由模型自决。
MULTI_AGENT_HINT = (
	"# Multi-Agent（background only）\n"
	"用户开启了 multi-agent（多代理）模式。"
)
