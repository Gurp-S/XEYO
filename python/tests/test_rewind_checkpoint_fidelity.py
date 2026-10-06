"""回滚前的安全副本 `_checkpoint_files` 必须逐字节忠实，且不许被编码问题炸掉。

缺陷（2026-10-03 实测复现并修复）：`_checkpoint_files` 用 `path.read_text(encoding="utf-8")`
取"最后一份副本"的内容，而同一函数里的 `content_hash` 来自 `read_bytes`。两个后果：

1. 非 UTF-8 的变更文件（GBK 导出的 CSV、别的编码的历史文件）⇒
   `UnicodeDecodeError`（它是 ValueError 的子类，**不是 OSError**）从 `_checkpoint_files` 逃逸。
   而这一枪打在 `execute()` 那个 try 的**外面**（`checkpoint = self._checkpoint_files(...)`）
   ⇒ 补偿用的 checkpoint 根本没建起来、job 状态与 audit 一条不留，整个回滚请求炸成裸 traceback。
2. `read_text(newline=None)` 把 `\\r\\n` 归一成 `\\n` ⇒ 快照存的不是磁盘那份。
   补偿写回（`_restore_checkpoint` → `_write_atomic`）时把用户的行尾翻掉。
   实测：`win.txt` 磁盘 `alpha\\r\\nbeta\\r\\n`，快照 `alpha\\nbeta\\n`。

修法：安全副本按**原始字节**存（`put_bytes`），写回也按字节（`get_bytes` + `_write_atomic` 收 bytes）。
写回这一腿单独钉住：文本口径（`get_text(encoding="utf-8")`）在 GBK 快照上抛 UnicodeDecodeError
⇒ 副本存对了却写不回去，补偿路径照样失败。
旧的文本快照条目仍能被 `get_bytes` 原样读回，不改变已有 job 的可恢复性。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rewind.service import RollbackService, _write_atomic  # noqa: E402

GBK_BYTES = "姓名,金额\n郭,12\n".encode("gb18030")
CRLF_BYTES = b"alpha\r\nbeta\r\n"
BOM_BYTES = "héllo\n".encode("utf-8-sig")


def _service(tmp_path: Path) -> RollbackService:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    return RollbackService("s1", ws, sessions_dir=sessions, enabled=True)


def _details(svc: RollbackService, names: list[str]) -> list[dict[str, object]]:
    return [
        {"path": str(Path(svc.workspace_root) / name), "operation_id": f"op{i}", "operation_type": "file_write"}
        for i, name in enumerate(names)
    ]


def test_non_utf8_file_does_not_crash_the_checkpoint(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    target = Path(svc.workspace_root) / "表.csv"
    target.write_bytes(GBK_BYTES)

    # 旧行为：UnicodeDecodeError 从这里逃逸（不是 OSError，调用点的 except 接不住）
    with pytest.raises(UnicodeDecodeError):
        target.read_text(encoding="utf-8")

    checkpoint = svc._checkpoint_files(_details(svc, ["表.csv"]), "job1")  # type: ignore[arg-type]
    assert len(checkpoint) == 1
    item = checkpoint[0]
    assert item["exists"] is True
    snap = svc.snapshots.get_bytes(str(item["snapshot_hash"]))
    assert snap == GBK_BYTES, "非 UTF-8 文件的安全副本必须逐字节等于磁盘"


def test_crlf_file_snapshot_keeps_line_endings(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    (Path(svc.workspace_root) / "win.txt").write_bytes(CRLF_BYTES)
    checkpoint = svc._checkpoint_files(_details(svc, ["win.txt"]), "job2")  # type: ignore[arg-type]
    snap = svc.snapshots.get_bytes(str(checkpoint[0]["snapshot_hash"]))
    assert snap == CRLF_BYTES, f"快照把 CRLF 归一掉了：{snap!r}"
    assert snap.startswith(b"alpha\r\n")


def test_bom_file_snapshot_keeps_bom(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    (Path(svc.workspace_root) / "bom.txt").write_bytes(BOM_BYTES)
    checkpoint = svc._checkpoint_files(_details(svc, ["bom.txt"]), "job3")  # type: ignore[arg-type]
    snap = svc.snapshots.get_bytes(str(checkpoint[0]["snapshot_hash"]))
    assert snap == BOM_BYTES


def test_compensation_restore_is_byte_exact(tmp_path: Path) -> None:
    """补偿写回（回滚做坏之后的 undo）落盘的字节必须等于原文件。"""
    svc = _service(tmp_path)
    path = Path(svc.workspace_root) / "win.txt"
    path.write_bytes(CRLF_BYTES)
    checkpoint = svc._checkpoint_files(_details(svc, ["win.txt"]), "job4")  # type: ignore[arg-type]

    # 回滚"做坏了"：内容被换成 LF 版（这正是旧 bug 会写回的形状）
    path.write_bytes(b"alpha\nbeta\n")
    errors = svc._restore_checkpoint(checkpoint, None)  # type: ignore[arg-type]
    assert errors == [], f"补偿恢复报错：{errors}"
    assert path.read_bytes() == CRLF_BYTES, f"补偿写回没有还原行尾：{path.read_bytes()!r}"


def test_compensation_restore_of_non_utf8_is_byte_exact(tmp_path: Path) -> None:
    """补偿写回也必须按字节：文本口径（`get_text(encoding="utf-8")`）在 GBK 快照上直接抛
    UnicodeDecodeError ⇒ 这份"最后一份副本"存对了却写不回去。"""
    svc = _service(tmp_path)
    path = Path(svc.workspace_root) / "表.csv"
    path.write_bytes(GBK_BYTES)
    checkpoint = svc._checkpoint_files(_details(svc, ["表.csv"]), "job4b")  # type: ignore[arg-type]

    path.write_bytes(b"corrupted by a half-applied rollback\n")
    errors = svc._restore_checkpoint(checkpoint, None)  # type: ignore[arg-type]
    assert errors == [], f"非 UTF-8 快照补偿写回失败：{errors}"
    assert path.read_bytes() == GBK_BYTES


def test_missing_snapshot_is_reported_not_silently_welcomed(tmp_path: Path) -> None:
    """反向对照：字节化不许把"快照读不出"变成沉默成功（旧文本口径同样会抛）。"""
    svc = _service(tmp_path)
    path = Path(svc.workspace_root) / "x.txt"
    path.write_bytes(b"one\r\n")
    checkpoint = svc._checkpoint_files(_details(svc, ["x.txt"]), "job5")  # type: ignore[arg-type]
    checkpoint[0]["snapshot_hash"] = "0" * 64  # 指向一份不存在的快照
    path.write_bytes(b"two\n")
    errors = svc._restore_checkpoint(checkpoint, None)  # type: ignore[arg-type]
    assert errors, "快照读不出却被当成补偿成功"
    assert path.read_bytes() == b"two\n", "读不出快照时不该动磁盘"


def test_write_atomic_still_accepts_text(tmp_path: Path) -> None:
    """transcript 等文本写回走的是同一把 writer：str 分支必须仍然有效。"""
    out = tmp_path / "t.jsonl"
    _write_atomic(out, '{"a": 1}\n')
    assert out.read_bytes() == b'{"a": 1}\n'
    _write_atomic(out, b'{"a": 2}\n')
    assert out.read_bytes() == b'{"a": 2}\n'


def test_directory_path_is_still_blocked(tmp_path: Path) -> None:
    """原有行为钉子：路径是目录 ⇒ RollbackBlockedError，不是崩溃。"""
    from rewind.service import RollbackBlockedError

    svc = _service(tmp_path)
    (Path(svc.workspace_root) / "dir").mkdir()
    with pytest.raises(RollbackBlockedError):
        svc._checkpoint_files(_details(svc, ["dir"]), "job6")  # type: ignore[arg-type]
