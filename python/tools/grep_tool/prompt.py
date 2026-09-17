GREP_TOOL_NAME = "Grep"

DESCRIPTION = """
Ripgrep content search. Filename search is exposed by Glob.
Regex; filter with path, glob, or type. Modes: files_with_matches (default), content, count, symbols.
Default excludes: node_modules/.git/.venv/dist/build/target/__pycache__ etc and .gitignore/.agentignore/secret files are auto-skipped (no need to add "!node_modules").
output_mode="symbols" lists matching symbol definitions (file:line: signature) from the symbol index.
Symbols detail="folded" groups methods under their containing class or type; detail="signatures" returns individual signatures. The kinds field filters values such as ["class", "interface"].
Single-line matches unless multiline=true. Escape literal braces.
"""
