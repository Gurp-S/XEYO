DIAGNOSTICS_TOOL_NAME = "Diagnostics"

DESCRIPTION = (
	"Best-effort language diagnostics on a required path (prefer the file you "
	"just edited). Uses ruff/py_compile for Python and tsc for TypeScript when "
	"those tools are available on PATH; otherwise it reports that no backend is "
	"available rather than guessing. Returns messages for the next turn. Not a "
	"full IDE/LSP. Do not omit path; do not use the workspace terminal for this."
)
