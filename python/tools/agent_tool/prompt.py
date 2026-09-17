"""Agent tool description and input/output facts."""

TOOL_NAME = "Agent"

DESCRIPTION = (
	"Spawn a short-lived scoped sub-agent (task-style isolation). "
	"Always available in Agent mode; the Multi-Agent chip is a separate session state.\n"
	"The sub-agent supports isolated or parallel work over multi-file scopes, "
	"independent directories, and research context. Multiple Agent calls in ONE turn "
	"run concurrently when their scopes are independent.\n"
	"Provide task_id, desc; optional scope (write paths this worker may touch; "
	"empty scope = read-only hard gate, no Write/Edit), required_tools "
	"(Read, Edit, Grep, Glob…), and reuse_agent_id to retry an existing sidechain.\n"
	"Sub-agents get Git and a readonly Bash sandbox (allowlist only; other commands "
	"are denied); Memory and nested Agents are unavailable. "
	"After tool_result messages, the parent agent produces the final user response."
)

# Composer Multi-Agent chip：挂到本轮 T_now。E2 裁决：只告知事实
# （用户开启了 multi-agent），不教模型怎么拆活——拆不拆、何时派由模型自决。
MULTI_AGENT_HINT = (
	"# Multi-Agent（background only）\n"
	"用户开启了 multi-agent（多代理）模式。"
)
