DIAGNOSTICS_TOOL_NAME = "Diagnostics"

DESCRIPTION = (
	"Best-effort language diagnostics on a required path. The path may be a file "
	"just edited. Uses ruff/py_compile for Python and tsc for TypeScript when "
	"those tools are available on PATH; otherwise it reports that no backend is "
	"available. Returns diagnostic messages. Not a full IDE/LSP; the workspace "
	"terminal is not used by this tool."
)
