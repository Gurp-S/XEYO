import locale
import os
import subprocess
from pathlib import Path
from typing import Any, List, Optional


class ShadowGitError(RuntimeError):
    """Base class for errors related to Shadow Git operations."""


def decode_git_bytes(data: bytes) -> str:
    """Decode git stdout/stderr without locking to a single codec.

    Modern git often emits UTF-8 paths, but Windows locales (GBK/cp936) and
    older tooling may emit other encodings. Try strict candidates in order;
    fall back to UTF-8 with surrogateescape so restore never sees empty trees.
    """
    if not data:
        return ""
    for encoding in _git_text_encodings():
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="surrogateescape")


def _git_text_encodings() -> list[str]:
    ordered: list[str] = ["utf-8"]
    for candidate in (
        locale.getpreferredencoding(False),
        "gb18030",
        "gbk",
        "cp936",
        "mbcs",
        "cp1252",
        "latin-1",
    ):
        if not candidate:
            continue
        name = str(candidate).strip()
        if not name or name.lower() in {"utf-8", "utf8", "ansi_x3.4-1968", "ascii"}:
            # utf-8 已在首位；ascii 对路径来说太窄。
            if name.lower() in {"utf-8", "utf8"}:
                continue
            if name.lower() in {"ansi_x3.4-1968", "ascii"}:
                continue
        if name not in ordered and name.lower() not in {e.lower() for e in ordered}:
            ordered.append(name)
    return ordered


class ShadowGit:
    """Manages the isolated .xy-shadow-git repository for workspace versioning."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        if not self.workspace_root.is_dir():
            raise FileNotFoundError(f"workspace root is not a directory: {self.workspace_root}")
        self.git_dir = self.workspace_root / ".xy-shadow-git"

    def _run(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        # 始终先捕获字节再协商编码——绝不钉死单一编解码器。
        raw = self._run_bytes(args, check=False)
        completed = subprocess.CompletedProcess(
            args=raw.args,
            returncode=raw.returncode,
            stdout=decode_git_bytes(raw.stdout or b""),
            stderr=decode_git_bytes(raw.stderr or b""),
        )
        if check and completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed

    def _run_bytes(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
        env = os.environ.copy()
        env["GIT_DIR"] = str(self.git_dir)
        env["GIT_WORK_TREE"] = str(self.workspace_root)
        return subprocess.run(
            ["git", *args],
            cwd=str(self.workspace_root),
            env=env,
            capture_output=True,
            text=False,
            check=check,
        )

    def init_if_needed(self) -> None:
        """Initialize the shadow git repository if it doesn't exist."""
        self.git_dir.mkdir(parents=True, exist_ok=True)
        git_marker = self.git_dir / "HEAD"
        if not git_marker.exists():
            self._run(["init", "--quiet"])
            self._run(["config", "core.autocrlf", "false"])
            self._run(["config", "core.ignorecase", "true"])
            self._run(["config", "user.name", "XEYO Shadow"])
            self._run(["config", "user.email", "shadow@xeyo.local"])

        # 即使目录已被其他组件先创建，也要配置 exclude 文件。
        info_dir = self.git_dir / "info"
        info_dir.mkdir(exist_ok=True)
        exclude_file = info_dir / "exclude"
        existing_excludes = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
        required_excludes = [".xy-shadow-git/", ".xy-trash/"]
        missing = [item for item in required_excludes if item not in existing_excludes]
        if missing:
            with exclude_file.open("a", encoding="utf-8") as handle:
                if existing_excludes and not existing_excludes.endswith("\n"):
                    handle.write("\n")
                handle.write("\n".join(missing) + "\n")

        # 更新用户主 git exclude 以忽略 shadow git。
        main_git_info = self.workspace_root / ".git" / "info"
        if main_git_info.is_dir():
            main_exclude = main_git_info / "exclude"
            try:
                content = main_exclude.read_text(encoding="utf-8") if main_exclude.exists() else ""
                additions = [item for item in required_excludes if item not in content]
                if additions:
                    with main_exclude.open("a", encoding="utf-8") as handle:
                        if content and not content.endswith("\n"):
                            handle.write("\n")
                        handle.write("\n".join(additions) + "\n")
            except Exception:
                pass

    def head_commit(self) -> Optional[str]:
        """Return the current HEAD commit hash, or None if no commits exist."""
        try:
            result = self._run(["rev-parse", "HEAD"], check=False)
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None

    def diff_paths(self, old_commit: str, new_commit: str) -> list[str]:
        """Return relative paths that differ between two commits (name-only)."""
        self.init_if_needed()
        old = str(old_commit or "").strip()
        new = str(new_commit or "").strip()
        if not old or not new:
            return []
        result = self._run_bytes(
            ["diff", "--name-only", "-z", old, new],
            check=False,
        )
        if result.returncode not in (0, 1):
            return []
        raw = result.stdout if isinstance(result.stdout, (bytes, bytearray)) else b""
        out: list[str] = []
        for item in bytes(raw).split(b"\0"):
            if not item:
                continue
            path = decode_git_bytes(item).replace("\\", "/").strip()
            if path:
                out.append(path)
        return out

    def snapshot(
        self,
        message: str = "Snapshot",
        *,
        paths: list[str] | None = None,
    ) -> str:
        """Create a new commit representing the current workspace state.

        When ``paths`` is provided, only those relative paths are staged
        (Rewind v2 scoped safety — no full-tree ``git add -A`` on restore).
        ``paths=None`` keeps the legacy full-worktree snapshot used by turn
        before/after hooks.
        """
        self.init_if_needed()
        if paths is not None:
            scoped = [
                str(p).replace("\\", "/").lstrip("./")
                for p in paths
                if str(p).strip()
            ]
            if not scoped:
                head = self.head_commit()
                if head:
                    return head
                self._run(["commit", "--allow-empty", "-m", message])
                head = self.head_commit()
                if not head:
                    raise ShadowGitError("Failed to retrieve HEAD after empty scoped commit")
                return head
            # 只暂存范围化路径；恢复热路径绝不 `add -A`。
            self._run(["add", "--", *scoped], check=False)
        else:
            self._run(["add", "-A"])

        status_result = self._run(["status", "--porcelain"], check=False)
        if not status_result.stdout.strip():
            head = self.head_commit()
            if head:
                return head

        self._run(["commit", "--allow-empty", "-m", message])
        head = self.head_commit()
        if not head:
            raise ShadowGitError("Failed to retrieve HEAD after commit")
        return head
