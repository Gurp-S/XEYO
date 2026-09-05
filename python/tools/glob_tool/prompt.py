GLOB_TOOL_NAME = "Glob"

DESCRIPTION = """
Find files by name/glob. Newest mtime first. Default root = cwd.
Respects .gitignore/.ignore, an optional workspace `.agentignore`, and built-in
excludes (node_modules, dist, .git, secret files).
Prefer a name fragment (e.g. *Map*.tsx) and set path when the subtree is known.
Do NOT use pattern `**/*` / `*` to explore — even directory-scoped like
`gui/**/*` — any pattern without a file-name fragment returns a one-level
directory summary only (scoped to the prefix directory when given).
head_limit: default 120 = hard cap. Truncated → "Too many matches": narrow the glob
(add a name/extension fragment) or set path; do not page through everything.
Empty first pass with letters in the pattern retries case-insensitively; if it is
still empty and a near-miss file/dir can be derived, a "Did you mean …" hint is
appended (directory and filename near-misses both covered).
Repeat queries within 60s are served from an in-memory cache (instant).
detail: auto (default, fold when many hits) | paths | folded.
Prefer Glob over Bash find; content search → Grep.
"""
