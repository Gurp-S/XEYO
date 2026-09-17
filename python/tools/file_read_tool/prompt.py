FILE_READ_TOOL_NAME = "Read"

FILE_UNCHANGED_STUB = (
	"File unchanged since last read. The earlier Read tool_result remains current."
)

MAX_LINES_TO_READ = 2000

DESCRIPTION_TEXT = f"""Reads a text file (absolute file_path). Default: first {MAX_LINES_TO_READ} lines; offset/limit address long files.
The symbol parameter returns one class/function body (for example, "MyClass.handle_request"). Ambiguous or missing symbols produce a symbol error; Grep output_mode="symbols" returns symbol definitions.
The symbol parameter with pack=true includes same-file context such as docstrings, imports, and signatures.
Output has line numbers starting at 1. Directories, images, PDF, Office, and binary files are rejected. Missing paths return an error; empty files return a warning."""

DESCRIPTION_VISION = f"""Reads a text or image file (absolute file_path). Text output defaults to the first {MAX_LINES_TO_READ} lines; offset/limit address long files.
Images (png/jpg/gif/webp) return as vision attachments (auto-resized). PDF pages use a 1-indexed offset and render when pymupdf is available.
Directories, Office files, archives, and other binaries are rejected."""

# 兼容旧 import
DESCRIPTION = DESCRIPTION_TEXT
