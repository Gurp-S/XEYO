"""Common project boundaries and rule discovery for static and nested inputs."""
from pathlib import Path


def workspace_root(cwd: str, explicit: str | None = None) -> str:
    start = Path(cwd or ".").expanduser().resolve()
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not start.is_relative_to(root):
            raise ValueError("instruction cwd outside workspace root")
        return str(root)
    # .git files cover worktrees too. Rule files alone do not prove a boundary.
    for directory in (start, *start.parents):
        if (directory / ".git").exists():
            return str(directory)
    return str(start)


def rule_files(directory: Path) -> list[Path]:
    files = [directory / "XEYO.md", directory / ".xeyo" / "XEYO.md"]
    files.extend(sorted((directory / ".xeyo" / "rules").glob("*.md")))
    files.extend([directory / "CLAUDE.md", directory / "AGENTS.md"])
    files.extend(sorted((directory / ".cursor" / "rules").glob("*.md")))
    return files


def nested_files(file_path: str, root_path: str, already=()) -> list[str]:
    import os
    root = Path(root_path).expanduser().resolve()
    start = Path(file_path).expanduser().resolve()
    if start.is_file():
        start = start.parent
    if not start.is_relative_to(root):
        return []
    have = {os.path.normcase(str(Path(p).resolve())) for p in already}
    found = []
    for directory in (start, *start.parents):
        if directory == root:
            break
        for path in rule_files(directory):
            key = os.path.normcase(str(path.resolve()))
            if path.is_file() and key not in have:
                have.add(key)
                found.append(str(path.resolve()))
    return found
