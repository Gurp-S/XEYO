"""回溯 v3 热路径事务：``POST /rewind`` 的 orphan → 原子重写 → 异步恢复。

崩溃顺序合同：**orphan → fsync → 原子替换 transcript → 再改工作区**。

- ``continue``：整轮（target user 消息及其回复/工具轨迹）写入
  ``orphans/{rewind_id}.jsonl``，随后原子重写 transcript 前缀；工作区恢复
  在后台线程执行，恢复前逐文件记录 ``pre_rewind_index`` 供 Undo。
- ``restore``：不改 transcript，仅后台恢复文件 + 审计。
- Undo：orphan 追加回 transcript + 按 ``pre_rewind_index`` 写回文件；
  有新消息落盘或路径被再次修改时拒绝/跳过（评审 #5）。

不依赖 shadow-git、不走 preview。v2 ``rewind.service`` 保持原样作降级路径。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rewind.index import (
    AgentFileIndex,
    FileCheckpoint,
    load_checkpoint,
)
from rewind.snapshot import SnapshotStore
from session.persistence import default_sessions_dir, safe_session_filename, transcript_path

__all__ = [
    "RewindHotpath",
    "RewindHotpathError",
    "RewindNotFoundError",
    "RewindStateError",
    "RewindValidationError",
    "mark_crashed_rewinds",
]

#: 进行中（未达终态）的 rewind 状态；启动时据此标记 recovery_required（§9.2）。
IN_FLIGHT_REWIND_STATUSES: frozenset[str] = frozenset({"transcript_committed", "restoring"})

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()

#: 后台文件恢复 worker 的按会话串行闸：两个 restore 并发写同一工作区
#  会产生混合终态、且后提交者的 pre_rewind_index 会拍到前者的中间态。
_RESTORE_LOCKS: dict[str, threading.Lock] = {}


def _lock_for(session_id: str) -> threading.RLock:
    key = session_id
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _restore_lock_for(session_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _RESTORE_LOCKS.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _RESTORE_LOCKS[session_id] = lock
        return lock


class RewindHotpathError(RuntimeError):
    """热路径失败基类；``code`` 供路由映射 HTTP 状态。"""

    code = "rewind_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = type(self).code


class RewindValidationError(RewindHotpathError):
    code = "rewind_invalid"


class RewindNotFoundError(RewindHotpathError):
    code = "rewind_not_found"


class RewindStateError(RewindHotpathError):
    code = "rewind_conflict"


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(str(path)):
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile_mkstemp_in(path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def tempfile_mkstemp_in(directory: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(prefix=".rewind-", dir=str(directory))


def _append_transcript(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _safe_resolve(root: Path, rel: str) -> Path | None:
    raw = str(rel or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or ":" in raw[:3]:
        return None
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.lstat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def _hash_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def mark_crashed_rewinds(sessions_dir: Path | None = None) -> int:
    """启动扫描：把「进行中但未达终态」的 rewind 事件标记为 ``recovery_required``（§9.2）。

    进程崩溃会打断后台恢复线程，transcript 已提交、工作区可能处于中间态。
    重启后把这些 in-flight 事件提升为可处理状态（重试/放弃），避免被当作已完成。
    """
    root = sessions_dir or default_sessions_dir()
    marked = 0
    if not root.is_dir():
        return marked
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        events_path = child / "rewind_events.jsonl"
        rows = _read_rows(events_path) if events_path.is_file() else []
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            rid = str(row.get("rewind_id") or "")
            if rid:
                latest[rid] = row
        for rid, row in latest.items():
            if str(row.get("status") or "") in IN_FLIGHT_REWIND_STATUSES:
                _append_event(
                    events_path,
                    {
                        **row,
                        "status": "recovery_required",
                        "error": str(row.get("error") or "进程重启：回溯未完成，需从检查点重试或放弃"),
                    },
                )
                marked += 1
        marked += _reconcile_orphan_surface_markers(child, events_path, latest)
    return marked


def _reconcile_orphan_surface_markers(
    session_child: Path,
    events_path: Path,
    latest_events: dict[str, dict[str, Any]],
) -> int:
    """46 号对账：transcript 里有 rewind marker、事件文件却没有对应事件。

    marker 追加成功但事件落盘前崩溃 → 该回溯在 fold 生效却无 pill/undo 入口。
    为其合成 ``transcript_committed`` 事件，让对话层有可撤销入口（无 checkpoint
    → 后续按 partial/no_checkpoint 终态规则呈现）。
    """
    from session.record_transcript import transcript_read_paths
    from session.surface import is_surface_marker

    # transcript 是与目录同名的 .jsonl 文件（<safe_name>.jsonl）。
    transcript = session_child.parent / f"{session_child.name}.jsonl"
    if not transcript.is_file():
        return 0
    known_ids = set(latest_events.keys())
    real_sid = ""
    for row in latest_events.values():
        real_sid = str(row.get("session_id") or "")
        if real_sid:
            break

    rows: list[dict[str, Any]] = []
    for p in transcript_read_paths(transcript):
        rows.extend(_read_rows(p))
    from session.surface import fold_surface_rows

    # 记录每个 rewind marker 行在原始日志中的位置，供重建「落地前一刻」可见面。
    marker_positions: list[tuple[int, dict[str, Any]]] = []
    for i, row in enumerate(rows):
        if is_surface_marker(row) and str(row.get("op") or "") == "rewind":
            marker_positions.append((i, row))
    synth = 0
    seen: set[str] = set()
    for pos, row in marker_positions:
        rid = str(row.get("rewind_id") or "")
        if not rid or rid in known_ids or rid in seen:
            continue
        seen.add(rid)
        # undo 守卫基准 = 该 marker 落地前一刻可见面中「影子起点的前一行」
        # （对齐 rewind()：target 自身也被移除，retained = folded[:target_idx]）。
        pre_visible = fold_surface_rows(rows[:pos])
        shadow_from = str(row.get("shadow_from") or "")
        after_id = ""
        for j, r in enumerate(pre_visible):
            if str(r.get("id") or "") == shadow_from and j > 0:
                after_id = str(pre_visible[j - 1].get("id") or "")
                break
        _append_event(
            events_path,
            {
                "rewind_id": rid,
                "session_id": real_sid or session_child.name,
                "mode": "continue",
                "ts": float(row.get("ts") or time.time()),
                "target_message_id": str(row.get("shadow_from") or ""),
                "checkpoint_id": "",
                "surface_marker": True,
                "orphan_id": "",
                "orphan_count": 0,
                "retained_row_count": 0,
                "after_message_id": after_id,
                "idempotency_key": "",
                "pill_summary": {"edited_digest": "", "removed_rows": 0},
                # 直接给终态 partial（无 checkpoint：仅截断对话、文件未回滚）。
                # 若置 transcript_committed 会被下次扫描当 in-flight 再标。
                "status": "partial",
                "restore": {
                    "restored": [],
                    "deleted": [],
                    "unchanged": [],
                    "skipped_dirty": [],
                    "failed": [],
                    "no_checkpoint": True,
                },
                "pre_rewind_index": [],
                "undone": False,
                "error": "由启动对账合成（事件落盘前崩溃）",
            },
        )
        synth += 1
    return synth


@dataclass
class RewindResult:
    """``rewind`` 的同步返回（transcript 已提交、恢复可能仍在后台）。"""

    rewind_id: str
    mode: str
    transcript_committed: bool
    removed_rows: int
    retained_rows: int
    checkpoint_id: str | None
    status: str
    reused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rewind_id": self.rewind_id,
            "mode": self.mode,
            "transcript_committed": self.transcript_committed,
            "removed_rows": self.removed_rows,
            "retained_rows": self.retained_rows,
            "checkpoint_id": self.checkpoint_id,
            "status": self.status,
            "reused": self.reused,
        }


class RewindHotpath:
    """会话作用域的热路径回溯事务（v3.1 合同实现）。"""

    def __init__(
        self,
        session_id: str,
        *,
        sessions_dir: Path | None = None,
        snapshots: SnapshotStore | None = None,
        workspace_root: Path | str | None = None,
    ) -> None:
        self.session_id = str(session_id or "").strip()
        if not self.session_id:
            raise ValueError("session_id is required")
        self.sessions_dir = sessions_dir or default_sessions_dir()
        self.snapshots = snapshots or SnapshotStore(self.session_id)
        self.workspace_root = Path(workspace_root) if workspace_root else None
        self._session_dir = self.sessions_dir / safe_session_filename(self.session_id)
        self.transcript = transcript_path(self.session_id, sessions_dir=self.sessions_dir)
        self.index = AgentFileIndex(self.session_id, sessions_dir=self.sessions_dir)

    # ------------------------------------------------------------------ 路径

    @property
    def events_path(self) -> Path:
        return self._session_dir / "rewind_events.jsonl"

    @property
    def orphans_dir(self) -> Path:
        return self._session_dir / "orphans"

    # ------------------------------------------------------------------ 事件

    def list_events(self) -> list[dict[str, Any]]:
        rows = _read_rows(self.events_path)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            rid = str(row.get("rewind_id") or "")
            if rid:
                latest[rid] = row
        return list(latest.values())

    def get_event(self, rewind_id: str) -> dict[str, Any] | None:
        rid = str(rewind_id or "")
        for row in self.list_events():
            if row.get("rewind_id") == rid:
                return row
        return None

    # ------------------------------------------------------------------ 回退

    def rewind(
        self,
        *,
        mode: str,
        target_message_id: str,
        checkpoint_id: str | None = None,
        edited_text: str | None = None,
        idempotency_key: str | None = None,
        confirmed: bool = False,
    ) -> RewindResult:
        """确认后执行：continue 同帧语义 = orphan 先落盘、transcript 原子重写。"""
        if not confirmed:
            raise RewindValidationError("rewind requires confirmed=true")
        mode = str(mode or "").strip()
        if mode not in {"restore", "continue"}:
            raise RewindValidationError(f"unsupported rewind mode: {mode!r}")
        if mode == "continue" and not str(edited_text or "").strip():
            raise RewindValidationError("continue requires edited_text")
        target = str(target_message_id or "").strip()
        if not target:
            raise RewindValidationError("target_message_id is required")

        with _lock_for(self.session_id):
            if idempotency_key:
                matching = [
                    event
                    for event in self.list_events()
                    if event.get("idempotency_key") == idempotency_key
                ]
                if matching:
                    # 只看最新一条：failed/undone/recovery_abandoned 是「键已释放」的
                    # 陈旧终态——重放它们会让调用方拿到与当前意图无关的旧结果
                    # （GUI pollSettled 也不认 undone，只会白等超时）。
                    latest = matching[-1]
                    if str(latest.get("status") or "") not in {
                        "failed",
                        "undone",
                        "recovery_abandoned",
                    }:
                        if (
                            latest.get("mode") != mode
                            or latest.get("target_message_id") != target
                        ):
                            raise RewindValidationError(
                                "idempotency_key reused for a different rewind"
                            )
                        return self._result_from_event(latest, reused=True)

            # replace 事件化（46 号）：读合并日志（含轮转归档）→ surface fold →
            # 在「模型可见面」中定位 target → 追加一条 rewind marker。
            # transcript 永不重写、不落 orphan；被回溯行留在原文件被影子化，
            # 崩溃最坏结果是 marker 半行写坏被读侧跳过 = 回溯视为未发生。
            try:
                from session.record_transcript import (
                    flush_pending_sync,
                    transcript_read_paths,
                )
                from session.surface import fold_surface_rows, rewind_marker_row

                flush_pending_sync(timeout=5.0)
                raw_rows: list[dict[str, Any]] = []
                for p in transcript_read_paths(self.transcript):
                    raw_rows.extend(_read_rows(p))
                folded = fold_surface_rows(raw_rows)
            except Exception as exc:  # noqa: BLE001 — fold 管线异常按目标缺失处理
                raise RewindNotFoundError(
                    f"transcript surface fold failed: {exc}"
                ) from exc

            target_idx = next(
                (
                    i
                    for i, row in enumerate(folded)
                    if str(row.get("id") or "") == target
                ),
                None,
            )
            if target_idx is None:
                raise RewindNotFoundError(
                    f"target message not in transcript: {target}"
                )

            rewind_id = f"rw_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
            if mode == "continue":
                orphan_rows = folded[target_idx:]
                retained_rows = folded[:target_idx]
                # 单行 marker 追加（fsync）：transcript_committed 的全部持久动作。
                _append_transcript(
                    self.transcript,
                    [rewind_marker_row(rewind_id, target)],
                )
            else:
                # restore 模式不动 transcript（含 marker）。
                orphan_rows = []
                retained_rows = folded

            edited = str(edited_text or "").strip()
            event = {
                "rewind_id": rewind_id,
                "session_id": self.session_id,
                "mode": mode,
                "ts": time.time(),
                "target_message_id": target,
                "checkpoint_id": checkpoint_id or "",
                "surface_marker": mode == "continue",
                "orphan_id": "",
                "orphan_count": len(orphan_rows),
                "retained_row_count": len(retained_rows),
                "after_message_id": (
                    str(retained_rows[-1].get("id") or "") if retained_rows else ""
                ),
                "idempotency_key": idempotency_key or "",
                "pill_summary": {
                    "edited_digest": edited[:64],
                    "removed_rows": len(orphan_rows),
                },
                "status": "transcript_committed" if mode == "continue" else "restoring",
                "restore": None,
                "pre_rewind_index": [],
                "undone": False,
                "error": None,
            }
            _append_event(self.events_path, event)
            self._spawn_restore(event)
            return RewindResult(
                rewind_id=rewind_id,
                mode=mode,
                transcript_committed=mode == "continue",
                removed_rows=len(orphan_rows),
                retained_rows=len(retained_rows),
                checkpoint_id=checkpoint_id,
                status=event["status"],
            )

    def _result_from_event(self, event: dict[str, Any], *, reused: bool) -> RewindResult:
        return RewindResult(
            rewind_id=str(event.get("rewind_id")),
            mode=str(event.get("mode")),
            # marker 事件即便 removed_rows=0（回溯到首条消息）也算已提交。
            transcript_committed=(
                bool(event.get("surface_marker")) or str(event.get("mode")) == "continue"
            ),
            removed_rows=int(event.get("orphan_count") or 0),
            retained_rows=int(event.get("retained_row_count") or 0),
            checkpoint_id=str(event.get("checkpoint_id") or "") or None,
            status=str(event.get("status")),
            reused=reused,
        )

    # ------------------------------------------------------------------ 恢复

    def _spawn_restore(self, event: dict[str, Any]) -> None:
        if not self.workspace_root:
            event = {**event, "status": "failed", "error": "workspace_root unavailable"}
            _append_event(self.events_path, event)
            return
        if not event.get("checkpoint_id"):
            # 无 checkpoint 也必须给终态：事件停在 transcript_committed/restoring
            # 会让前端 pollSettled 只能等超时（然后误判「未确认」并回滚列表）。
            # - continue：对话确实截断了，但**没有文件检查点**可恢复。
            #   不能置 committed（前端会当作「文件已恢复」而给「后台恢复中/已恢复」
            #   的误导文案）；置 partial + no_checkpoint 标记，让前端明确提示
            #   「仅截断对话，文件未回滚」。
            # - restore：没有可恢复对象 → failed（UI 正常路径会先禁用 Restore）。
            if str(event.get("mode") or "") == "continue":
                event = {
                    **event,
                    "status": "partial",
                    "restore": {
                        "restored": [],
                        "deleted": [],
                        "unchanged": [],
                        "skipped_dirty": [],
                        "failed": [],
                        "written": [],
                        "no_checkpoint": True,
                    },
                }
            else:
                event = {**event, "status": "failed", "error": "no checkpoint to restore"}
            _append_event(self.events_path, event)
            return
        thread = threading.Thread(
            target=self._restore_worker,
            args=(dict(event),),
            name=f"rewind-restore-{event.get('rewind_id')}",
            daemon=True,
        )
        thread.start()

    def _restore_worker(self, event: dict[str, Any]) -> None:
        # 同会话的 restore 必须串行：快速连续两次回溯会 spawn 两个 worker，
        # 并发 _write_atomic_bytes 的终态取决于调度，undo 的哈希守卫还会把
        # 混合态判 skipped_dirty。后到 worker 等待前者完成后再拍 pre_index。
        with _restore_lock_for(self.session_id):
            self._restore_worker_locked(event)

    def _restore_worker_locked(self, event: dict[str, Any]) -> None:
        try:
            report, pre_index = self._restore_checkpoint_files(
                str(event.get("checkpoint_id") or "")
            )
        except Exception as exc:  # noqa: BLE001 — 恢复失败必须落事件而不是抛出
            # 恢复中间态：工作区可能已写了一半，只能用「从检查点重试 / 放弃」。
            _append_event(
                self.events_path,
                {
                    **event,
                    "status": "recovery_required",
                    "error": str(exc),
                    "restore": None,
                },
            )
            return
        skipped = report.get("skipped_dirty") or []
        failures = report.get("failed") or []
        if failures:
            # 部分文件未能恢复 → 工作区处于中间态，需显式处理（§9.2）。
            status = "recovery_required"
        elif skipped:
            # 仅用户手改路径被跳过（预期行为）→ partial，可视为成功。
            status = "partial"
        else:
            status = "committed"
        _append_event(
            self.events_path,
            {
                **event,
                "status": status,
                "restore": report,
                "pre_rewind_index": pre_index,
            },
        )

    def _journal_before_hash(self, rel: str) -> str | None:
        """查该会话 journal，判断某路径是否「既有文件被 agent 修改」。

        删除分支的防御（BUG-1 数据丢失）：一个检查点冻结前**从未被索引、但本轮被
        agent 首次修改**的既有用户文件，不在 checkpoint.entries、却在 index.entries，
        会落入删除分支被 ``unlink``。这类文件在 mutation 时 ``existed_before=True``，
        journal 里 ``before_hash`` 非空（``inverse_kind='restore_snapshot'``）。凡是存在
        此类记录，就应**恢复 before 内容**而非删除。返回 before 内容哈希；纯新建文件
        （``before_hash is None``）返回 None，仍走删除。

        方向安全：宁可多恢复、绝不误删用户文件（I7 用户数据安全）。
        """
        try:
            ops = _read_rows(self._session_dir / "operations.jsonl")
        except Exception:  # noqa: BLE001 — journal 不可读则保守：不删除
            return ""
        root = self.workspace_root
        if root is None:
            return ""
        try:
            abs_path = str((root / rel).resolve())
        except Exception:  # noqa: BLE001
            return ""
        for row in ops:
            if str(row.get("status") or "") != "completed":
                continue
            if str(row.get("path") or "").replace("\\", "/") != abs_path.replace("\\", "/"):
                continue
            bh = row.get("before_hash")
            if bh:
                return str(bh)
        return ""

    def _restore_checkpoint_files(
        self, checkpoint_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        cp = load_checkpoint(
            self.session_id, checkpoint_id, sessions_dir=self.sessions_dir
        )
        if cp is None:
            raise RewindNotFoundError(f"checkpoint not found: {checkpoint_id}")
        assert self.workspace_root is not None
        root = self.workspace_root
        index_entries = self.index.entries()
        report: dict[str, Any] = {
            "restored": [],
            "deleted": [],
            "unchanged": [],
            "skipped_dirty": [],
            "failed": [],
            "written": [],
        }
        pre_index: list[dict[str, Any]] = []

        for rel in sorted(cp.entries):
            cp_hash = cp.entries[rel]
            full = _safe_resolve(root, rel)
            if full is None or not cp_hash:
                report["failed"].append(rel)
                continue
            try:
                self._restore_one_file(
                    root, rel, full, cp_hash, index_entries, report, pre_index
                )
            except OSError as exc:
                report["failed"].append(f"{rel}: {exc}")

        # checkpoint 之后 agent 新建、且此后未被手改的路径 → 删除。
        # BUG-1 防御：一个「检查点冻结前从未被索引、但本轮被 agent 首次修改」的既有
        # 用户文件不在 cp.entries、却在 index.entries，会被当成「新建」删除。先查 journal：
        # 若该路径存在「既有文件被修改」（before_hash 非空）记录，则恢复 before 内容，
        # 绝不删除（I7 用户数据安全，方向安全宁可多恢复）。
        for rel, entry in sorted(index_entries.items()):
            if rel in cp.entries or not entry.content_hash:
                continue
            full = _safe_resolve(root, rel)
            if full is None or not full.is_file():
                continue
            if _file_signature(full) != (entry.size, entry.mtime_ns):
                report["skipped_dirty"].append(rel)
                continue
            try:
                data = full.read_bytes()
            except OSError as exc:
                report["failed"].append(f"{rel}: {exc}")
                continue
            now_hash = _hash_bytes(data)
            before_hash = self._journal_before_hash(rel)
            if before_hash:
                # 既有文件被 agent 首次修改：恢复 before 内容，不删除。
                try:
                    content = self.snapshots.get_bytes(before_hash)
                except (OSError, KeyError) as exc:
                    report["failed"].append(f"{rel}: {exc}")
                    continue
                pre_index.append(
                    {"path": rel, "hash": now_hash, "existed": True}
                )
                try:
                    _write_atomic_bytes(full, content)
                    stat = full.lstat()
                    self.index.upsert(
                        rel,
                        content_hash=before_hash,
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                        source="restore_writeback",
                    )
                    report["restored"].append(rel)
                    report["written"].append({"path": rel, "hash_written": before_hash})
                except OSError as exc:
                    report["failed"].append(f"{rel}: {exc}")
                continue
            pre_index.append(
                {"path": rel, "hash": now_hash, "existed": True}
            )
            try:
                full.unlink()
                self.index.upsert(
                    rel,
                    content_hash=None,
                    size=0,
                    mtime_ns=0,
                    source="restore_writeback",
                )
                report["deleted"].append(rel)
                report["written"].append({"path": rel, "hash_written": None})
            except OSError as exc:
                report["failed"].append(f"{rel}: {exc}")
        return report, pre_index

    def _restore_one_file(
        self,
        root: Path,
        rel: str,
        full: Path,
        cp_hash: str,
        index_entries: dict[str, Any],
        report: dict[str, Any],
        pre_index: list[dict[str, Any]],
    ) -> None:
        exists = full.is_file()
        current_hash: str | None = None
        if exists:
            current_hash = _hash_bytes(full.read_bytes())
            if current_hash == cp_hash:
                report["unchanged"].append(rel)
                return
            entry = index_entries.get(rel)
            # managed 判定改用内容哈希，而不是 (size, mtime) 签名：
            # 索引同步失败 / turn 基线截断 / 文件在 turn 后再次被触碰（格式化/lint/编辑器）
            # 都会造成 size/mtime 漂移；若仍用签名判定，会把合法的 agent 改动误判为
            # 「用户手改」而跳过恢复（回溯无作用）。内容哈希匹配即说明文件仍由 agent 掌控。
            managed = (
                entry is not None
                and entry.content_hash is not None
                and current_hash == entry.content_hash
            )
            if not managed and current_hash != cp_hash:
                # 用户手改（评审合同：跳过，弹窗提示）。
                report["skipped_dirty"].append(rel)
                return
        try:
            content = self.snapshots.get_bytes(cp_hash)
        except (OSError, KeyError) as exc:
            report["failed"].append(f"{rel}: {exc}")
            return
        pre_index.append({"path": rel, "hash": current_hash, "existed": exists})
        _write_atomic_bytes(full, content)
        stat = full.lstat()
        self.index.upsert(
            rel,
            content_hash=cp_hash,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            source="restore_writeback",
        )
        report["restored"].append(rel)
        report["written"].append({"path": rel, "hash_written": cp_hash})

    # ------------------------------------------------------------------ 撤销

    def undo(self, rewind_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise RewindValidationError("undo requires confirmed=true")
        with _lock_for(self.session_id):
            event = self.get_event(rewind_id)
            if event is None:
                raise RewindNotFoundError(f"rewind event not found: {rewind_id}")
            if event.get("undone"):
                raise RewindStateError("rewind already undone")
            if event.get("status") not in {"committed", "partial"}:
                raise RewindStateError(
                    f"rewind not undoable in status {event.get('status')!r}"
                )

            result: dict[str, Any] = {"rewind_id": rewind_id, "conversation": None, "files": None}

            if event.get("mode") == "continue":
                self._undo_conversation(event, result)
            self._undo_files(event, result)

            _append_event(
                self.events_path,
                {**event, "status": "undone", "undone": True, "undo": result},
            )
            result["status"] = "undone"
            return result

    # ------------------------------------------------------------------ 找回

    def recover(
        self,
        rewind_id: str,
        *,
        action: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """处理 ``recovery_required`` 中间态（§9.2）。

        - ``retry``：从检查点重新恢复（幂等）；status 回到 ``restoring``，后台线程重跑。
        - ``abandon``：保留当前磁盘内容，标记终态 ``recovery_abandoned``。
        """
        if not confirmed:
            raise RewindValidationError("recover requires confirmed=true")
        action = str(action or "").strip()
        with _lock_for(self.session_id):
            event = self.get_event(rewind_id)
            if event is None:
                raise RewindNotFoundError(f"rewind event not found: {rewind_id}")
            if str(event.get("status") or "") != "recovery_required":
                raise RewindStateError(
                    f"rewind not in recovery_required: {event.get('status')!r}"
                )
            if action == "abandon":
                _append_event(
                    self.events_path,
                    {**event, "status": "recovery_abandoned", "recovery": {"action": "abandon"}},
                )
                return {"rewind_id": rewind_id, "status": "recovery_abandoned"}
            if action == "retry":
                if not self.workspace_root or not event.get("checkpoint_id"):
                    raise RewindStateError("cannot retry recovery: no checkpoint/workspace")
                attempt = int(event.get("recovery_attempt") or 0) + 1
                new_event = {
                    **event,
                    "status": "restoring",
                    "error": None,
                    "recovery_attempt": attempt,
                    "recovery": {"action": "retry", "attempt": attempt},
                }
                _append_event(self.events_path, new_event)
                self._spawn_restore(new_event)
                return {"rewind_id": rewind_id, "status": "restoring"}
            raise RewindValidationError(f"unsupported recovery action: {action!r}")

    def _undo_conversation(
        self, event: dict[str, Any], result: dict[str, Any]
    ) -> None:
        if event.get("surface_marker"):
            self._undo_conversation_marker(event, result)
            return
        self._undo_conversation_legacy(event, result)

    def _undo_conversation_marker(
        self, event: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """marker 事件：conversation undo = 追加一条 rewind_undo marker。

        原子单行追加，无半途状态：写前已 undo（重试续跑）→ 跳过；
        marker 写成功但 `_undo_files` 失败 → 重试时 `has_undo_marker`
        判定续跑，只重做文件部分。undo 守卫 = fold 后可见面末行必须
        等于事件的 ``after_message_id``（等价旧「行数守卫」且对轮转健壮）。
        """
        try:
            from session.record_transcript import (
                flush_pending_sync,
                transcript_read_paths,
            )
            from session.surface import (
                fold_surface_rows,
                has_undo_marker,
                rewind_undo_marker_row,
            )

            flush_pending_sync(timeout=5.0)
            raw_rows: list[dict[str, Any]] = []
            for p in transcript_read_paths(self.transcript):
                raw_rows.extend(_read_rows(p))
        except Exception as exc:  # noqa: BLE001
            raise RewindStateError(f"transcript unreadable for undo: {exc}") from exc

        if has_undo_marker(raw_rows, str(event.get("rewind_id") or "")):
            # 前次 undo 已把对话恢复、但文件部分失败 → 续跑只做文件。
            result["conversation"] = {"restored": 0, "resumed": True, "reason": None}
            return

        folded = fold_surface_rows(raw_rows)
        last_visible = str(folded[-1].get("id") or "") if folded else ""
        if last_visible != str(event.get("after_message_id") or ""):
            # 评审 #5：rewind 后有新 turn 落盘，恢复会造成乱序对话。
            raise RewindStateError("new messages since rewind; undo blocked")

        _append_transcript(
            self.transcript, [rewind_undo_marker_row(str(event.get("rewind_id") or ""))]
        )
        result["conversation"] = {
            "restored": int(event.get("orphan_count") or 0),
            "resumed": False,
            "reason": None,
        }

    def _undo_conversation_legacy(
        self, event: dict[str, Any], result: dict[str, Any]
    ) -> None:
        """遗留（46 号之前）orphan 事件：行在 orphan 文件里，物理回放。"""
        orphan_id = str(event.get("orphan_id") or "")
        orphan_path = self.orphans_dir / f"{orphan_id}.jsonl" if orphan_id else None
        if orphan_path is None or not orphan_path.is_file():
            result["conversation"] = {"restored": 0, "reason": "orphan missing"}
            return
        orphan_rows = _read_rows(orphan_path)
        current = _read_rows(self.transcript)
        orphan_ids = {
            str(row.get("id") or "") for row in orphan_rows if row.get("id")
        }
        current_ids = {str(row.get("id") or "") for row in current}
        overlap = orphan_ids & current_ids
        if overlap:
            # 半途 undo 的续跑：前次尝试已把 orphan（可能部分）回放进 transcript
            # 后在 _undo_files 抛错。这里绝不能 409 卡死——只补缺失的行继续。
            missing = [
                row
                for row in orphan_rows
                if str(row.get("id") or "") not in current_ids
            ]
        else:
            if len(current) != int(event.get("retained_row_count") or 0):
                # 评审 #5：rewind 后有新 turn 落盘，恢复会造成乱序对话。
                raise RewindStateError("new messages since rewind; undo blocked")
            missing = list(orphan_rows)
        if missing:
            _append_transcript(self.transcript, missing)
        result["conversation"] = {
            "restored": len(missing),
            "resumed": bool(overlap),
            "reason": None,
        }

    def _undo_files(self, event: dict[str, Any], result: dict[str, Any]) -> None:
        if not self.workspace_root:
            result["files"] = {"restored": 0, "skipped_dirty": [], "reason": "workspace_root unavailable"}
            return
        restore_report = event.get("restore") or {}
        written = {
            item.get("path"): item
            for item in (restore_report.get("written") or [])
        }
        restored = 0
        skipped: list[str] = []
        for pre in event.get("pre_rewind_index") or []:
            rel = str(pre.get("path") or "")
            full = _safe_resolve(self.workspace_root, rel)
            if full is None:
                continue
            info = written.get(rel) or {}
            current_hash = _hash_bytes(full.read_bytes()) if full.is_file() else None
            if current_hash != info.get("hash_written"):
                # 评审 #5：恢复后路径又被改动（可能来自新 turn）→ 跳过。
                skipped.append(rel)
                continue
            pre_hash = pre.get("hash")
            if pre_hash is None:
                if full.exists():
                    full.unlink()
                    restored += 1
                else:
                    restored += 1
                self.index.upsert(rel, content_hash=None, size=0, mtime_ns=0, source="undo_writeback")
                continue
            content = self.snapshots.get_bytes(pre_hash)
            if current_hash == pre_hash:
                restored += 1
                continue
            _write_atomic_bytes(full, content)
            stat = full.lstat()
            self.index.upsert(
                rel,
                content_hash=pre_hash,
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                source="undo_writeback",
            )
            restored += 1
        result["files"] = {"restored": restored, "skipped_dirty": skipped, "reason": None}


def _write_atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile_mkstemp_in(path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
