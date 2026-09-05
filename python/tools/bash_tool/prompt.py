BASH_TOOL_NAME = "Bash"

DESCRIPTION = """
Run a shell command — ONLY when no dedicated tool fits: build/test/install,
package managers, process/network tools, git writes.
NEVER for file ops (they have dedicated tools): list -> Glob, content search ->
Grep, read -> Read, edit -> Edit, create/overwrite -> Write, read-only git -> Git.
Shell is PowerShell (7 when available, else Windows PowerShell 5.1). No bash-isms:
- POSIX tools are usually absent (grep/sed/awk/head/tail/wc/which/xargs report
  "not recognized"): use Select-String, Get-Content -Head/-Tail,
  Select-Object -First/-Last, Measure-Object, Get-Command instead; filter
  objects with Where-Object/ForEach-Object, not grep|awk pipelines.
- Redirection/env: 2>$null (not 2>/dev/null); $env:VAR (not $VAR, not export).
- Quoting: double quotes expand $var and backtick escapes; single quotes are
  literal — always single-quote regex args, e.g. rg 'error$' file.
- && and || work on PowerShell 7 only; on 5.1 split into separate calls.
command required; timeout ms (default 120000, max 600000). A foreground command
still running after ~45s is auto-moved to a background job: you get the job id
plus partial output immediately, and a completion notification later (read with
job_output). Use run_in_background=true up front for known-long jobs.
Optional working_directory (relative to session cwd; must stay in workspace).
Noisy test/build/git stdout is compacted for the model; failures are kept.
"""
