"""Worktree administrative updates share a repository, not an index."""
from pathlib import Path

from coord.locking import FileGuard


def metadata_guard(repo: Path, git_call, *, timeout: float) -> FileGuard:
    common = Path(git_call(repo, "rev-parse", "--git-common-dir").stdout.strip())
    if not common.is_absolute():
        common = repo / common
    # Creation may first remove an old worktree: four bounded Git commands.
    return FileGuard(common.resolve() / "xeyo-worktrees.lock", timeout=timeout, ttl=6 * timeout)
