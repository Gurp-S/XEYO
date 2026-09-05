GIT_TOOL_NAME = "Git"

DESCRIPTION = (
	"Read-only git: summary (prefer), status, log, branches, or file diff. "
	"Prefer summary for a quick overview; when dirty, summary includes touched: "
	"symbols whose lines intersect the diff. "
	"Prefer over Bash for these. No commit/push/add — use Bash (ASK) for writes."
)

WRITE_REJECT = (
	"Git tool is read-only. action=commit|push|add|… is not supported. "
	"Use Bash with an explicit git write command (requires user ASK)."
)
