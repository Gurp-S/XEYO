GLOB_TOOL_NAME = "Glob"

DESCRIPTION = """
Find files by name/glob. Newest mtime first. Default root = cwd.
Respects .gitignore/.ignore, an optional workspace `.agentignore`, and built-in
excludes (node_modules, dist, .git, secret files).
Name fragments (e.g. *Map*.tsx) and path roots are supported. Patterns without
a file-name fragment, including `**/*` / `*` and directory-scoped `gui/**/*`,
return a one-level directory summary only (scoped to the prefix directory when
given); git
tracking state is surfaced as fact: directories with zero git-tracked files
carry an `untracked` marker plus their newest file mtime date; mixed
directories list only `N untracked` (no date); fully tracked directories
stay silent.
head_limit: default 120 = hard cap. Truncated responses contain "Too many matches"
and the truncation state.
Empty first pass with letters in the pattern retries case-insensitively; if it is
still empty and a near-miss file/dir can be derived, a nearest-name hint is
appended (directory and filename near-misses both covered).
Repeat queries within 60s are served from an in-memory cache (instant).
detail: auto (default, fold when many hits) | paths | folded.
Glob and Bash both expose file listing; content search is exposed by Grep.
"""
