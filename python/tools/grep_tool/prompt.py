GREP_TOOL_NAME = "Grep"

DESCRIPTION = """
Ripgrep content search — use instead of Bash grep/rg. For filenames use Glob.
Regex; filter with path, glob, or type. Modes: files_with_matches (default), content, count, symbols.
Default excludes: node_modules/.git/.venv/dist/build/target/__pycache__ etc and .gitignore/.agentignore/secret files are auto-skipped (no need to add "!node_modules").
output_mode="symbols" lists matching symbol definitions (file:line: signature) from the symbol index — prefer it over content when looking for classes/functions/structure.
Symbols strategy: scope to a subdirectory first; use detail="folded" for repo-wide overviews (methods collapsed into containers); expand interesting containers via Read symbol="Class.method" or by narrowing path with detail="signatures". Use kinds to filter e.g. ["class", "interface"].
Single-line matches unless multiline=true. Escape literal braces.
"""
