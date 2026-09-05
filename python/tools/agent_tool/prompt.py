"""Agent tool description (when to spawn a sub-agent)."""

TOOL_NAME = "Agent"

DESCRIPTION = (
	"Spawn a short-lived scoped sub-agent (Cursor/Claude Code Task style). "
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

# Composer Multi-Agent chip：挂到本轮 T_now，软偏向（不裁剪工具、不拦截收尾）。
MULTI_AGENT_HINT = (
	"# Multi-Agent preference（用户已打开）\n"
	"本回合优先用 Agent 工具拆活，而不是自己在主线程做完所有搜索/编辑。\n"
	"何时 spawn：\n"
	"- 两个以上互不重叠的目录/文件/子问题 → **同回合多次**调用 Agent（可并行），"
	"不要「派一个→等结果→再派」串行浪费轮次\n"
	"- 探索范围大、怕污染主对话上下文 → 交给子 Agent，拿 tool_result 再答\n"
	"何时自己干：一句话问答、单文件小改、已读内容足够直接回答。\n"
	"先用 Glob/Read 摸一眼可以；摸清边界后仍要拆时，立刻 Agent，勿把整活做完。\n"
	"每个 Agent 写清 task_id + desc；有写路径就填**窄** scope（勿用 `.` 全仓）。\n"
	"所有 Agent 的 tool_result 回来后，由你汇总写最终回答（勿再开分解流水线）。"
)
