from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from pathlib import Path

from engine.shadow_git import ShadowGit


class WorkspaceRevision:
    """Calculate a conservative, metadata-only workspace fingerprint.

    When ``paths`` is provided, only those relative paths are fingerprinted
    (plus shadow HEAD).  That keeps Vite/test churn outside the rollback plan
    from invalidating ``expected_workspace_revision``.

    Without ``paths``, git status identifies changed paths and we add ``lstat``
    metadata rather than reading file contents.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.shadow_git = ShadowGit(self.workspace_root)

    @staticmethod
    def _status_path(line: str) -> tuple[str, str] | None:
        if len(line) < 4:
            return None
        status = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[-1]
        return status, path

    @staticmethod
    def normalize_paths(paths: Iterable[str] | None) -> tuple[str, ...]:
        if paths is None:
            return ()
        seen: list[str] = []
        for raw in paths:
            text = str(raw or "").replace("\\", "/").strip().lstrip("./")
            if text and text not in seen:
                seen.append(text)
        return tuple(seen)

    def _metadata_token(self, status: str, relative_path: str) -> str:
        candidate = (self.workspace_root / relative_path).resolve(strict=False)
        try:
            relative = candidate.relative_to(self.workspace_root)
        except ValueError:
            return f"{status}\0{relative_path}\0outside-workspace"

        try:
            stat = os.lstat(candidate)
        except FileNotFoundError:
            return f"{status}\0{relative.as_posix()}\0missing"
        except OSError as exc:
            return f"{status}\0{relative.as_posix()}\0error:{type(exc).__name__}"

        if os.path.islink(candidate):
            try:
                link_target = os.readlink(candidate)
            except OSError:
                link_target = "<unreadable>"
            kind = f"symlink:{link_target}"
        elif os.path.isdir(candidate):
            kind = "directory"
        else:
            kind = "file"
        return (
            f"{status}\0{relative.as_posix()}\0{kind}\0{stat.st_size}"
            f"\0{stat.st_mtime_ns}\0{stat.st_ctime_ns}\0{stat.st_mode}"
        )

    def calculate(self, paths: Iterable[str] | None = None) -> str:
        """Calculate the current workspace revision without a content scan.

        ``paths=()`` (empty iterable) fingerprints shadow HEAD only — suitable
        for chat-only rollback where unrelated worktree noise must not block.
        ``paths=None`` keeps the legacy full porcelain fingerprint.
        """
        self.shadow_git.init_if_needed()
        head = self.shadow_git.head_commit() or "empty"
        metadata: list[str] = []
        if paths is not None:
            for relative_path in self.normalize_paths(paths):
                metadata.append(self._metadata_token("SC", relative_path))
        else:
            status_result = self.shadow_git._run(
                ["status", "--porcelain=v1", "--untracked-files=normal"],
                check=False,
            )
            status_text = (
                status_result.stdout if status_result.returncode == 0 else "<status-error>"
            )
            for line in status_text.splitlines():
                parsed = self._status_path(line)
                if parsed is not None:
                    metadata.append(self._metadata_token(*parsed))
        metadata.sort()

        hasher = hashlib.sha256()
        hasher.update(head.encode("utf-8"))
        hasher.update(b"\0")
        for token in metadata:
            hasher.update(token.encode("utf-8", errors="surrogateescape"))
            hasher.update(b"\0")
        return f"rev_{hasher.hexdigest()[:16]}"
