"""memindex_sig_shadow — 【侧挂模块·默认关】memindex 签名从 (mtime,size) 改为 (size, content_sha)。

依据：memindex 签名口径一致性设计（侧挂 ⑧.5：记忆索引签名 (mtime,size) → (size,content_sha)）。

## 为什么（收益目标）
- `memindex._sync_table` 现状用 `(mtime, size)` 做懒同步签名；`mtime` 在 Windows/部分
  文件系统是秒级粗粒度——同秒内编辑（内容变、size 未必变）会漏检/误检。
- `codeindex.symbols.py` 已明示「不依赖 mtime（规避 Windows 同秒粗粒度）」，用
  `(size, content_hash)`。本模块把记忆侧 notes 表对齐到同一哲学。

## 侧挂契约（不改主文件逻辑）
- `enabled()`：读 `XEYO_MEMINDEX_SIG_HASH`（默认 0=关）。开=notes 走 `(size, sha)` 签名；
  关=`_sync_table` 原逻辑（逐位不变）。
- `install()` / `uninstall()`：挂钩 `memindex._sync_table`（`load_notes_cached` /
  `load_rollouts_cached` 均经它）。卸载即恢复原函数，零源改动。
- **fail-open**：签名/读文件任何异常 → 抛给调用方 `load_notes` 回退文件扫描（P0 词法召回
  永不回归，与 `memindex.py` 既有语义一致）。

## 范围与承诺
- **仅 notes 表**用 `(size, sha)`。notes 已有 `sha` 列；其值由本模块在 INSERT 时写为
  「文件原始字节的 sha」→ 与签名比较同一量，未变文件命中签名→跳过（零解析/零重插）。
- rollouts 表**无 sha 列**，改动需 schema 迁移，超出「不改当前代码」范畴 → **rollouts
  仍走原 `(mtime,size)` 逻辑**，本模块不碰。
- **读代价（诚实透明）**：开启后每个候选 note 文件**读一次**算 `(size, sha)`；真正重活
  （`parse_and_validate` / 正文 re-insert）只对「内容变更」文件发生。收益门槛性能探针
  （`test_memindex_sig_shadow.py::test_read_cost_probe`）量化这份「每同步多读一次」的代价，
  与「同秒编辑不漏检」的收益权衡；代价过大则不升格。

## 自一致性（迁移）
- 首次在已由原逻辑建库的环境 install：DB 里存的 `sha` = `_sha(fm_json+body)`（解析后），
  与本模块「文件原始字节 sha」不是一个量 → 首轮全量重读迁移一次，此后自洽。
"""

from __future__ import annotations

import hashlib
import importlib
import os
import time

_TARGET_MODULE = "memory.memindex"
_HOOK_NAME = "_sync_table"
_ENV = "XEYO_MEMINDEX_SIG_HASH"
_SHA_LEN = 32

#: 目标模块对象（install 时绑定）。模块级仅一个引用，卸载时清空。
_TARGET = None
_ORIG_NAME = "_ORIG__sync_table"
_INSTALLED_FLAG = "__memindex_sig_installed"


def enabled() -> bool:
    """是否启用内容哈希签名（升格后默认开；专用 env / 全局 promote 可关）。"""
    from sidecar.policy import side_enabled

    return side_enabled(_ENV)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:_SHA_LEN]


def install() -> bool:
    """挂钩 `memindex._sync_table`；返回是否实际安装（仅已启用才装）。"""
    if not enabled():
        return False
    mod = importlib.import_module(_TARGET_MODULE)
    global _TARGET
    if not getattr(mod, _INSTALLED_FLAG, False):
        if not hasattr(mod, _ORIG_NAME):
            setattr(mod, _ORIG_NAME, getattr(mod, _HOOK_NAME))
        setattr(mod, _HOOK_NAME, _sync_table_content_hash)
        setattr(mod, _INSTALLED_FLAG, True)
    _TARGET = mod
    return True


def uninstall() -> None:
    """卸载挂钩点，恢复原 `_sync_table`。"""
    global _TARGET
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    if getattr(mod, _INSTALLED_FLAG, False):
        setattr(mod, _HOOK_NAME, getattr(mod, _ORIG_NAME))
        setattr(mod, _INSTALLED_FLAG, False)
    _TARGET = None


def _sync_table_content_hash(
    domain: str,
    table: str,
    directory,
    *,
    loader,
) -> None:
    """内容哈希签名版 `_sync_table`。只对 notes 表生效；rollouts 委托原逻辑。"""
    if table != "notes" or _TARGET is None:
        orig = getattr(_TARGET or importlib.import_module(_TARGET_MODULE), _ORIG_NAME)
        return orig(domain, table, directory, loader=loader)
    _sync_notes_content_hash(domain, directory, loader=loader)


def _sync_notes_content_hash(domain: str, directory, *, loader) -> None:
    """notes 的内容哈希签名同步：比较 (size, sha)，命中即跳过，否则重跑 loader。"""
    entries = _dir_signature_content_hash(directory)
    conn = _TARGET._connect(domain)  # noqa: SLF001
    try:
        # 与原 memindex._sync_table 一致：用 try/finally + 显式 commit（sqlite3 连接在
        # 无 `with` 时默认不自动提交，close() 会回滚未提交事务）。因此手动 commit。
        cur = conn.execute("SELECT path, size, sha FROM notes WHERE domain = ?", (domain,))
        known: dict[str, tuple[int, str]] = {
            row[0]: (int(row[1] or 0), str(row[2] or "")) for row in cur.fetchall()
        }
        for name, (size, sha) in entries.items():
            if known.get(name) == (size, sha):
                continue  # 内容哈希命中 → 零解析/零重插
            full = directory / name
            loaded = loader(full)
            if loaded is None:
                conn.execute("DELETE FROM notes WHERE domain = ? AND path = ?", (domain, name))
                continue
            fm_json, body = loaded
            conn.execute(
                "INSERT OR REPLACE INTO notes(domain, path, mtime, size, sha, fm_json, body)"
                " VALUES (?,?,?,?,?,?,?)",
                (domain, name, _now(), size, sha, fm_json, body),
            )
        for name in known:
            if name not in entries:
                conn.execute("DELETE FROM notes WHERE domain = ? AND path = ?", (domain, name))
        conn.execute(
            "INSERT OR REPLACE INTO meta(k, v) VALUES ('schema_version', ?)",
            (str(getattr(_TARGET, "_SCHEMA_VERSION", 1)),),
        )
        conn.commit()
    finally:
        conn.close()


def _dir_signature_content_hash(directory) -> dict[str, tuple[int, str]]:
    """``{文件名: (size, sha_raw)}``；目录不存在/异常返回空（fail-open）。"""
    out: dict[str, tuple[int, str]] = {}
    if not directory.is_dir():
        return out
    try:
        with os.scandir(directory) as it:
            for ent in it:
                if not ent.name.endswith(".md") or not ent.is_file():
                    continue
                full = os.path.join(directory, ent.name)
                try:
                    with open(full, "rb") as f:
                        data = f.read()
                    out[ent.name] = (len(data), _sha256(data.decode("utf-8", "replace")))
                except (OSError, UnicodeDecodeError):
                    continue
    except OSError:
        return out
    return out


def _now() -> float:
    return time.time()
