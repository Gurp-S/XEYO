FILE_READ_TOOL_NAME = "Read"

FILE_UNCHANGED_STUB = (
	"File unchanged since last read. The content from the earlier Read "
	"tool_result in this conversation is still current — refer to that "
	"instead of re-reading."
)

MAX_LINES_TO_READ = 2000

DESCRIPTION_TEXT = f"""Read a text file (absolute file_path). Default: first {MAX_LINES_TO_READ} lines; use offset/limit for long files.
To see just one class/function, pass symbol (e.g. "MyClass.handle_request") instead of offset/limit — returns only that symbol's body. If ambiguous/not found, use Grep with output_mode="symbols" to list names first.
To understand a symbol with same-file context (docstring, used imports, callee/caller signatures), pass symbol with pack=true.
cat -n output (line numbers from 1). Not for directories (use Glob/Bash). Rejects images, PDF, Office, and binary. Missing path → error (ok to probe); empty file → warning."""

DESCRIPTION_VISION = f"""Read a text or image file (absolute file_path). Text: first {MAX_LINES_TO_READ} lines; offset/limit for long files.
Images (png/jpg/gif/webp): returned as vision attachments (auto-resized). PDF: page via offset (1-indexed page); renders when pymupdf is available.
Not for directories. Rejects Office/archives/other binaries."""

# 兼容旧 import
DESCRIPTION = DESCRIPTION_TEXT
