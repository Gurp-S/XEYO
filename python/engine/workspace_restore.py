from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from engine.shadow_git import ShadowGit, _git_text_encodings, decode_git_bytes
from engine.workspace_lock import WorkspaceLock
from engine.workspace_revision import WorkspaceRevision


class RestoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class _TreeEntry:
    mode: str
    object_type: str
    object_hash: str


@dataclass(frozen=True)
class _CurrentEntry:
    exists: bool
    is_directory: bool = False
    is_symlink: bool = False
    object_hash: str | None = None


class WorkspaceRestoreTransaction:
    """Restore a Shadow Git tree without silently overwriting external edits.

    ``trash_candidates`` is intentionally explicit.  A missing target path is
    moved to ``.xy-trash`` only when the prepare layer has classified it as an
    Agent-created/untracked artifact; unspecified paths are left untouched.
    """

    WAL_FILENAME = "restore-wal.jsonl"
    TERMINAL_PHASES = frozenset({"COMMITTED", "RECOVERED", "RECOVERY_REQUIRED"})

    def __init__(self, workspace_root: str | Path, owner: str) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        if not self.workspace_root.is_dir():
            raise FileNotFoundError(f"workspace root is not a directory: {self.workspace_root}")
        self.owner = owner
        self.shadow_git = ShadowGit(self.workspace_root)
        self.revision = WorkspaceRevision(self.workspace_root)
        self.lock = WorkspaceLock(self.workspace_root, owner=owner)
        self.wal_path = self.workspace_root / ".xy-shadow-git" / self.WAL_FILENAME

    def _append_wal(self, payload: dict[str, object], *, durable: bool = False) -> None:
        """Append a WAL record.  ``durable=True`` fsyncs (start/end only)."""
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        record = dict(payload)
        record.setdefault("timestamp", time.time())
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        with self.wal_path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            if durable:
                os.fsync(handle.fileno())

    def _read_wal(self) -> list[dict[str, object]]:
        if not self.wal_path.is_file():
            return []
        records: list[dict[str, object]] = []
        with self.wal_path.open("rb") as handle:
            for raw in handle:
                try:
                    value = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(value, dict) and value.get("transaction_id"):
                    records.append(value)
        return records

    @staticmethod
    def _latest_wal(records: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
        latest: dict[str, dict[str, object]] = {}
        for record in records:
            transaction_id = str(record.get("transaction_id") or "")
            if transaction_id:
                latest[transaction_id] = record
        return latest

    def _validate_relative_path(self, relative_path: str) -> Path:
        normalized = str(relative_path).replace("\\", "/")
        pure = PurePosixPath(normalized)
        if not normalized or pure.is_absolute() or ".." in pure.parts:
            raise RestoreError(f"unsafe workspace path: {relative_path!r}")
        candidate = self.workspace_root.joinpath(*pure.parts)
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise RestoreError(f"workspace path escapes root: {relative_path!r}") from exc
        cursor = self.workspace_root
        for part in pure.parts[:-1]:
            cursor = cursor / part
            if os.path.islink(cursor):
                raise RestoreError(f"symlink parent is not restorable: {relative_path!r}")
        return candidate

    def _tree_entries(self, commit: str) -> dict[str, _TreeEntry]:
        result = self.shadow_git._run_bytes(["ls-tree", "-r", "-z", commit], check=False)
        if result.returncode != 0:
            stderr = decode_git_bytes(result.stderr or b"").strip()
            raise RestoreError(f"invalid Shadow Git target {commit!r}: {stderr}")
        raw = result.stdout if isinstance(result.stdout, (bytes, bytearray)) else b""
        entries: dict[str, _TreeEntry] = {}
        for item in bytes(raw).split(b"\0"):
            if not item:
                continue
            try:
                metadata_b, path_b = item.split(b"\t", 1)
                metadata = metadata_b.decode("ascii")
                mode, object_type, object_hash = metadata.split(" ", 2)
            except (ValueError, UnicodeDecodeError) as exc:
                raise RestoreError("Shadow Git tree contains an invalid entry") from exc
            path = self._decode_tree_path(path_b)
            self._validate_relative_path(path)
            if mode.startswith("120") or object_type != "blob":
                raise RestoreError(f"symlink or non-file target is not restorable: {path}")
            entries[path] = _TreeEntry(mode, object_type, object_hash)
        return entries

    def _decode_tree_path(self, path_b: bytes) -> str:
        """Decode one ls-tree path; prefer codecs whose result exists on disk."""
        # -z 模式下带引号形态罕见，但出于安全仍保留反转义。
        text_candidates: list[str] = []
        seen: set[str] = set()
        for encoding in _git_text_encodings():
            try:
                text = path_b.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                continue
            if text not in seen:
                seen.add(text)
                text_candidates.append(text)
        negotiated = decode_git_bytes(path_b)
        if negotiated not in seen:
            text_candidates.append(negotiated)

        resolved: list[str] = []
        for text in text_candidates:
            path = text
            if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
                path = self._unescape_git_path(path[1:-1])
            if path not in resolved:
                resolved.append(path)

        for path in resolved:
            try:
                candidate = self._validate_relative_path(path)
            except RestoreError:
                continue
            if os.path.lexists(candidate):
                return path
        # 磁盘未命中（删除/恢复路径的常态）：以第一个有效者为准。
        for path in resolved:
            try:
                self._validate_relative_path(path)
                return path
            except RestoreError:
                continue
        raise RestoreError(f"cannot decode Shadow Git path: {path_b!r}")

    @staticmethod
    def _unescape_git_path(path: str) -> str:
        """Decode git C-style path quoting (\\nnn octal and backslash escapes)."""
        simple = {
            "a": "\a",
            "b": "\b",
            "t": "\t",
            "n": "\n",
            "v": "\v",
            "f": "\f",
            "r": "\r",
            "\\": "\\",
            '"': '"',
        }
        out: list[int] = []
        i = 0
        while i < len(path):
            ch = path[i]
            if ch != "\\" or i + 1 >= len(path):
                out.extend(ch.encode("utf-8", errors="surrogateescape"))
                i += 1
                continue
            nxt = path[i + 1]
            if nxt in simple:
                out.extend(simple[nxt].encode("latin-1"))
                i += 2
                continue
            if nxt in "01234567" and i + 3 < len(path):
                octal = path[i + 1 : i + 4]
                if all(c in "01234567" for c in octal):
                    out.append(int(octal, 8))
                    i += 4
                    continue
            out.extend(nxt.encode("utf-8", errors="surrogateescape"))
            i += 2
        raw = bytes(out)
        return decode_git_bytes(raw)

    def _git_blob_hash(self, data: bytes) -> str:
        header = f"blob {len(data)}\0".encode("ascii")
        return hashlib.sha1(header + data).hexdigest()

    def _current_entry(self, relative_path: str) -> _CurrentEntry:
        candidate = self._validate_relative_path(relative_path)
        if not os.path.lexists(candidate):
            return _CurrentEntry(False)
        if os.path.islink(candidate):
            return _CurrentEntry(True, is_symlink=True)
        if candidate.is_dir():
            return _CurrentEntry(True, is_directory=True)
        try:
            data = candidate.read_bytes()
        except OSError as exc:
            raise RestoreError(f"cannot read workspace file {relative_path!r}") from exc
        return _CurrentEntry(True, object_hash=self._git_blob_hash(data))

    def _read_target_bytes(self, commit: str, relative_path: str) -> bytes:
        result = self.shadow_git._run_bytes(
            ["cat-file", "blob", f"{commit}:{relative_path}"], check=False
        )
        if result.returncode != 0:
            raise RestoreError(f"cannot read Shadow Git object for {relative_path!r}")
        return result.stdout

    def _make_writable(self, path: Path) -> None:
        try:
            mode = path.stat().st_mode
            if not mode & stat.S_IWUSR:
                os.chmod(path, mode | stat.S_IWUSR)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise RestoreError(f"cannot make path writable: {path}") from exc

    def _atomic_write(
        self,
        relative_path: str,
        data: bytes,
        mode: str,
        *,
        fsync: bool = False,
    ) -> None:
        target = self._validate_relative_path(relative_path)
        if os.path.lexists(target) and (os.path.islink(target) or target.is_dir()):
            raise RestoreError(f"cannot replace non-file path: {relative_path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._make_writable(target)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(data)
                handle.flush()
                if fsync:
                    os.fsync(handle.fileno())
            os.replace(temp_name, target)
            try:
                os.chmod(target, int(mode[-3:], 8))
            except OSError:
                pass
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def _remove_file(self, relative_path: str) -> None:
        target = self._validate_relative_path(relative_path)
        if not os.path.lexists(target):
            return
        if os.path.islink(target) or target.is_dir():
            raise RestoreError(f"cannot remove non-file path: {relative_path!r}")
        self._make_writable(target)
        target.unlink()

    def _move_to_trash(self, relative_path: str, trash_dir: Path) -> None:
        source = self._validate_relative_path(relative_path)
        if not os.path.lexists(source):
            return
        if os.path.islink(source):
            raise RestoreError(f"symlink is not eligible for trash: {relative_path!r}")
        destination = trash_dir.joinpath(*PurePosixPath(relative_path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_root = trash_dir.resolve()
        if not destination.resolve(strict=False).is_relative_to(destination_root):
            raise RestoreError(f"trash path escapes root: {relative_path!r}")
        if os.path.lexists(destination):
            raise RestoreError(f"trash destination already exists: {relative_path!r}")
        shutil.move(str(source), str(destination))

    def _restore_trash(self, moved_paths: Iterable[str], trash_dir: Path) -> None:
        for relative_path in moved_paths:
            source = trash_dir.joinpath(*PurePosixPath(relative_path).parts)
            if not os.path.lexists(source):
                continue
            destination = self._validate_relative_path(relative_path)
            if os.path.lexists(destination):
                raise RestoreError(f"cannot recover trash; destination exists: {relative_path!r}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))

    def _restore_tree_conditionally(
        self,
        *,
        source_commit: str,
        expected_tree: dict[str, _TreeEntry],
        target_tree: dict[str, _TreeEntry],
        removable_paths: set[str],
        moved_paths: set[str] | None = None,
        allow_target_created_cleanup: bool = False,
    ) -> None:
        moved_paths = moved_paths or set()
        all_paths = sorted(set(expected_tree) | set(target_tree))
        for relative_path in all_paths:
            expected = expected_tree.get(relative_path)
            target = target_tree.get(relative_path)
            current = self._current_entry(relative_path)
            if current.is_symlink:
                raise RestoreError(f"symlink encountered during restore: {relative_path!r}")
            if current.is_directory:
                raise RestoreError(f"directory encountered during restore: {relative_path!r}")

            expected_hash = expected.object_hash if expected else None
            target_hash = target.object_hash if target else None
            if expected is not None and current.exists and current.object_hash not in {
                expected_hash,
                target_hash,
            }:
                raise RestoreError(f"workspace changed during restore: {relative_path!r}")

            if target is not None:
                if current.object_hash == target_hash:
                    continue
                if expected is None or current.object_hash != expected_hash:
                    raise RestoreError(f"conditional write failed: {relative_path!r}")
                data = self._read_target_bytes(source_commit, relative_path)
                self._atomic_write(relative_path, data, target.mode)
                continue

            if relative_path in moved_paths:
                continue
            if relative_path in removable_paths:
                if current.object_hash != expected_hash:
                    raise RestoreError(f"conditional remove failed: {relative_path!r}")
                self._remove_file(relative_path)
            elif allow_target_created_cleanup and current.object_hash == target_hash:
                self._remove_file(relative_path)

    def _rollback_to_safety(
        self,
        *,
        safety_commit: str,
        target_commit: str,
        trash_dir: Path,
        moved_paths: set[str],
    ) -> None:
        safety_tree = self._tree_entries(safety_commit)
        target_tree = self._tree_entries(target_commit)
        self._restore_trash(moved_paths, trash_dir)
        self._restore_tree_conditionally(
            source_commit=safety_commit,
            expected_tree=target_tree,
            target_tree=safety_tree,
            removable_paths=set(target_tree) - set(safety_tree),
            allow_target_created_cleanup=True,
        )
        self.shadow_git.snapshot("Recovery snapshot after failed restore")

    def execute(
        self,
        target_commit: str,
        expected_revision: str,
        *,
        trash_candidates: Iterable[str] = (),
        auto_trash_created: bool = False,
        path_scope: Iterable[str] | None = None,
        fingerprint_paths: Iterable[str] | None = None,
        fault_inject: Callable[[str], None] | None = None,
    ) -> str:
        """Restore a target tree under a revision-checked workspace lock.

        When ``auto_trash_created`` is true (confirmed rewind), files present in
        the safety snapshot but absent from ``target_commit`` are moved to
        ``.xy-trash`` — covering agent-created files even if the journal missed
        them.

        ``path_scope`` limits restore/trash to the given relative paths (plus any
        explicit ``trash_candidates``).  ``None`` means the full tree union.

        ``fingerprint_paths`` scopes the expected-revision check; when omitted,
        falls back to ``path_scope`` (or full workspace if that is also None).
        """
        transaction_id = f"restore_{uuid.uuid4().hex}"
        trash_dir = self.workspace_root / ".xy-trash" / transaction_id
        moved_paths: set[str] = set()
        safety_commit: str | None = None
        target_tree: dict[str, _TreeEntry] = {}
        safety_tree: dict[str, _TreeEntry] = {}
        scope: set[str] | None = None
        if path_scope is not None:
            scope = {str(p).replace("\\", "/") for p in path_scope if str(p).strip()}
        rev_paths: list[str] | None
        if fingerprint_paths is not None:
            rev_paths = list(WorkspaceRevision.normalize_paths(fingerprint_paths))
        elif scope is not None:
            rev_paths = sorted(scope)
        else:
            rev_paths = None
        base_record: dict[str, object] = {
            "transaction_id": transaction_id,
            "target_commit": target_commit,
            "expected_revision": expected_revision,
            "phase": "PREPARING",
            "moved_paths": [],
            "path_scope": sorted(scope) if scope is not None else None,
            "fingerprint_paths": rev_paths,
        }

        with self.lock.hold(blocking=False):
            self._append_wal(base_record, durable=True)
            try:
                current_revision = self.revision.calculate(paths=rev_paths)
                if current_revision != expected_revision:
                    raise RestoreError(
                        f"Workspace changed: expected {expected_revision}, got {current_revision}"
                    )
                # 范围化：一次树遍历后只用 ls-tree 过滤；路径集较小时
                # 优先用路径清单，避免为安全暂存而哈希整个 commit。
                full_target = self._tree_entries(target_commit)
                if scope is not None:
                    target_tree = {k: v for k, v in full_target.items() if k in scope}
                else:
                    target_tree = full_target
                candidates = {
                    str(path).replace("\\", "/") for path in trash_candidates
                }
                if scope is not None:
                    candidates &= scope
                for relative_path in candidates:
                    self._validate_relative_path(relative_path)

                # Rewind v2：范围化安全——恢复热路径绝不 `git add -A`。
                safety_paths = sorted(set(scope or []) | set(candidates)) if scope is not None else None
                safety_commit = self.shadow_git.snapshot(
                    f"Safety snapshot before restoring {target_commit}",
                    paths=safety_paths,
                )
                full_safety = self._tree_entries(safety_commit)
                if scope is not None:
                    safety_tree = {
                        k: v
                        for k, v in full_safety.items()
                        if k in scope or k in candidates
                    }
                    # 包含仅存在于单侧的范围化路径。
                    for path in scope:
                        if path in full_safety and path not in safety_tree:
                            safety_tree[path] = full_safety[path]
                        if path in full_target and path not in target_tree:
                            target_tree[path] = full_target[path]
                else:
                    safety_tree = full_safety
                if auto_trash_created:
                    created = {
                        path for path in safety_tree if path not in full_target
                    }
                    if scope is not None:
                        created &= scope
                    candidates |= created
                safety_ref = f"refs/xeyo/safety/{transaction_id}"
                self.shadow_git._run(["update-ref", safety_ref, safety_commit])
                self._append_wal(
                    {
                        **base_record,
                        "phase": "SAFETY_SAVED",
                        "safety_commit": safety_commit,
                        "safety_ref": safety_ref,
                        "trash_dir": str(trash_dir),
                    }
                )
                if fault_inject:
                    fault_inject("SAFETY_SAVED")

                removable_paths = {
                    path for path in candidates if path in safety_tree and path not in target_tree
                }
                for relative_path in sorted(removable_paths):
                    current = self._current_entry(relative_path)
                    expected = safety_tree[relative_path]
                    if current.object_hash != expected.object_hash:
                        raise RestoreError(f"trash precondition failed: {relative_path!r}")
                    self._move_to_trash(relative_path, trash_dir)
                    moved_paths.add(relative_path)
                self._append_wal(
                    {
                        **base_record,
                        "phase": "TRASH_MOVED",
                        "safety_commit": safety_commit,
                        "safety_ref": safety_ref,
                        "trash_dir": str(trash_dir),
                        "moved_paths": sorted(moved_paths),
                    }
                )
                if fault_inject:
                    fault_inject("TRASH_MOVED")

                # 范围化时只触碰范围并集，不动整棵树。
                restore_expected = safety_tree
                restore_target = target_tree
                if scope is not None:
                    union = set(scope) | set(candidates) | set(moved_paths)
                    restore_expected = {k: v for k, v in safety_tree.items() if k in union}
                    restore_target = {k: v for k, v in target_tree.items() if k in union}

                self._restore_tree_conditionally(
                    source_commit=target_commit,
                    expected_tree=restore_expected,
                    target_tree=restore_target,
                    removable_paths=removable_paths,
                    moved_paths=moved_paths,
                )
                self._append_wal(
                    {
                        **base_record,
                        "phase": "TREE_RESTORED",
                        "safety_commit": safety_commit,
                        "safety_ref": safety_ref,
                        "trash_dir": str(trash_dir),
                        "moved_paths": sorted(moved_paths),
                    }
                )
                if fault_inject:
                    fault_inject("TREE_RESTORING")

                # 恢复后：仅范围化快照（与安全阶段同一路径集）。
                new_head = self.shadow_git.snapshot(
                    f"Restored workspace to {target_commit}",
                    paths=safety_paths,
                )
                workspace_ref = "refs/xeyo/workspace"
                self.shadow_git._run(["update-ref", workspace_ref, new_head])
                final_revision = self.revision.calculate(paths=rev_paths)
                self._append_wal(
                    {
                        **base_record,
                        "phase": "COMMITTED",
                        "safety_commit": safety_commit,
                        "safety_ref": safety_ref,
                        "workspace_ref": workspace_ref,
                        "new_head": new_head,
                        "final_revision": final_revision,
                        "trash_dir": str(trash_dir),
                        "moved_paths": sorted(moved_paths),
                    },
                    durable=True,
                )
                return final_revision
            except Exception as exc:
                if safety_commit is None:
                    self._append_wal({**base_record, "phase": "FAILED", "error": str(exc)})
                    if isinstance(exc, RestoreError):
                        raise
                    raise RestoreError(str(exc)) from exc
                try:
                    self._rollback_to_safety(
                        safety_commit=safety_commit,
                        target_commit=target_commit,
                        trash_dir=trash_dir,
                        moved_paths=moved_paths,
                    )
                except Exception as recovery_error:
                    self._append_wal(
                        {
                            **base_record,
                            "phase": "RECOVERY_REQUIRED",
                            "safety_commit": safety_commit,
                            "trash_dir": str(trash_dir),
                            "moved_paths": sorted(moved_paths),
                            "error": f"{exc}; recovery failed: {recovery_error}",
                        }
                    )
                    raise RestoreError("restore failed and recovery requires attention") from recovery_error
                self._append_wal(
                    {
                        **base_record,
                        "phase": "RECOVERED",
                        "safety_commit": safety_commit,
                        "trash_dir": str(trash_dir),
                        "moved_paths": sorted(moved_paths),
                        "error": str(exc),
                    }
                )
                raise RestoreError(f"Restore failed, rolled back to safety: {exc}") from exc

    def reconcile(self) -> list[str]:
        """Recover WAL transactions that did not reach a terminal commit."""
        recovered: list[str] = []
        latest = self._latest_wal(self._read_wal())
        with self.lock.hold(blocking=False):
            for transaction_id, record in latest.items():
                phase = str(record.get("phase") or "")
                if phase in self.TERMINAL_PHASES:
                    continue
                safety_commit = str(record.get("safety_commit") or "")
                target_commit = str(record.get("target_commit") or "")
                if not safety_commit or not target_commit:
                    self._append_wal({**record, "phase": "FAILED", "error": "no safety snapshot"})
                    continue
                moved_paths = {str(path) for path in record.get("moved_paths", [])}
                trash_dir = Path(str(record.get("trash_dir") or ""))
                try:
                    self._rollback_to_safety(
                        safety_commit=safety_commit,
                        target_commit=target_commit,
                        trash_dir=trash_dir,
                        moved_paths=moved_paths,
                    )
                except Exception as exc:
                    self._append_wal(
                        {**record, "phase": "RECOVERY_REQUIRED", "error": str(exc)}
                    )
                    continue
                self._append_wal({**record, "phase": "RECOVERED"})
                recovered.append(transaction_id)
        return recovered
