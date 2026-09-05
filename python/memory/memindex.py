"""memindex — 记忆清单的 sqlite 派生索引（A4）+ 压缩碎片还原存储（A2）+ 因果边表（C1 地基）。

**定位铁律：sqlite 只是派生索引/缓存；文件（memdir topics/*.md、rollout_summaries/*.md、
session.md、转录 JSONL）永远是 source of truth。** 库可随时删除并全量重建，零数据丢失风险。

三张职责：
1. notes / rollouts 签名缓存（A4 第一步）：按 (mtime, size) 签名懒同步，查询不再每次
   全量读+解析所有 md 文件；任何 sqlite 异常由调用方 fail-open 回退文件扫描（P0 词法召回
   永不回归）。评分逻辑不变——仍用 memory/search.py 的 Python 词法评分。
2. fragments（A2 retrieve 还原）：C2 压缩时把左区被折叠的**结构化原子**（stack/kv/path/
   json/tree/table）按 ``notes:msg:<绝对下标>`` 存全文；Memory(action=retrieve) 按锚点 id
   字节级找回。转录是最终真相，fragments 只是压缩时点的抓拍。
3. edges（C1 地基）：tool_use→tool_result 因果边等，供未来 DAG 钻取（本轮只建表+写入）。

开关（默认见 memory_switches 注册表）：
- 签名缓存（A4）：**已固化开启**（原 ``XEYO_MEMORY_SQLITE_INDEX`` 键已删，查询
  异常 fail-open 回退纯文件扫描）。
- fragments 抓取与 retrieve（A2）：**已固化开启**（原 ``XEYO_MEMORY_RESTORE`` 键已删）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: 每次压缩最多入库的结构化原子条数（防天量 tool_result 撑爆库）。
FRAGMENT_ROW_CAP = 400
#: 单条 fragment 正文上限（字节级还原的截断线，超出说明不该靠 retrieve 而该靠工具重跑）。
FRAGMENT_TEXT_CAP = 4096

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
  domain TEXT NOT NULL,
  path TEXT NOT NULL,
  mtime REAL NOT NULL,
  size INTEGER NOT NULL,
  sha TEXT NOT NULL,
  fm_json TEXT NOT NULL,
  body TEXT NOT NULL,
  PRIMARY KEY (domain, path)
);
CREATE TABLE IF NOT EXISTS rollouts (
  domain TEXT NOT NULL,
  path TEXT NOT NULL,
  mtime REAL NOT NULL,
  size INTEGER NOT NULL,
  raw TEXT NOT NULL,
  PRIMARY KEY (domain, path)
);
CREATE TABLE IF NOT EXISTS fragments (
  session_id TEXT NOT NULL,
  msg_index INTEGER NOT NULL,
  kind TEXT NOT NULL,
  seq INTEGER NOT NULL,
  text TEXT NOT NULL,
  sha TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (session_id, msg_index, kind, seq)
);
CREATE TABLE IF NOT EXISTS edges (
  session_id TEXT NOT NULL,
  from_msg INTEGER NOT NULL,
  to_msg INTEGER NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (session_id, from_msg, to_msg, kind)
);
CREATE INDEX IF NOT EXISTS idx_fragments_session ON fragments(session_id, msg_index);
"""


def sqlite_index_enabled() -> bool:
    """A4 签名缓存：**已固化开启**（收益明确过验收，不再是开关）。

    原开关 ``XEYO_MEMORY_SQLITE_INDEX`` 已移出 memory_switches 注册表；
    查询路径任何异常仍 fail-open 回退纯文件扫描（行为与逐文件解析等价）。
    回退只能改本函数源码。
    """
    return True


def restore_enabled() -> bool:
    """A2 压缩碎片还原：**已固化开启**（原 XEYO_MEMORY_RESTORE 键已删，回退只能改源码）。"""
    return True


def db_path(domain: str) -> Path:
    """库文件：``<memdir 根>/<domain>/index.sqlite3``（与 memdir 同域隔离）。"""
    from memory.memdir import memdir_root

    return memdir_root(domain) / "index.sqlite3"


def _connect(domain: str) -> sqlite3.Connection:
    path = db_path(domain)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=2.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=2000")
    conn.executescript(_SCHEMA_SQL)
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:32]


# --------------------------------------------------------------------------- #
# notes / rollouts 签名缓存（A4 第一步）
# --------------------------------------------------------------------------- #

def _dir_entries(directory: Path) -> dict[str, tuple[float, int]]:
    """目录内 *.md 的 {文件名: (mtime, size)}；目录不存在返回空。"""
    out: dict[str, tuple[float, int]] = {}
    if not directory.is_dir():
        return out
    try:
        with os.scandir(directory) as it:
            for ent in it:
                if not ent.name.endswith(".md") or not ent.is_file():
                    continue
                st = ent.stat()
                out[ent.name] = (st.st_mtime, st.st_size)
    except OSError:
        return out
    return out


def _sync_table(
    domain: str,
    table: str,
    directory: Path,
    *,
    loader,
) -> None:
    """按 (mtime, size) 签名把目录同步进 db：只重新读取变化的文件。"""
    entries = _dir_entries(directory)
    with _connect(domain) as conn:
        cur = conn.execute(
            f"SELECT path, mtime, size FROM {table} WHERE domain = ?", (domain,)
        )
        known = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
        for name, (mtime, size) in entries.items():
            if known.get(name) == (mtime, size):
                continue
            full = directory / name
            loaded = loader(full)
            if loaded is None:
                # 解析失败（如坏 frontmatter）→ 与文件扫描语义一致：不入库（跳过）
                conn.execute(
                    f"DELETE FROM {table} WHERE domain = ? AND path = ?", (domain, name)
                )
                continue
            payload = loaded  # (fm_json, body) 或 (raw,)
            if table == "notes":
                fm_json, body = payload
                conn.execute(
                    "INSERT OR REPLACE INTO notes(domain, path, mtime, size, sha, fm_json, body)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (domain, name, mtime, size, _sha(fm_json + body), fm_json, body),
                )
            else:
                (raw,) = payload
                conn.execute(
                    "INSERT OR REPLACE INTO rollouts(domain, path, mtime, size, raw)"
                    " VALUES (?,?,?,?,?)",
                    (domain, name, mtime, size, raw),
                )
        for name in known:
            if name not in entries:
                conn.execute(
                    f"DELETE FROM {table} WHERE domain = ? AND path = ?", (domain, name)
                )
        conn.execute(
            "INSERT OR REPLACE INTO meta(k, v) VALUES ('schema_version', ?)",
            (str(_SCHEMA_VERSION),),
        )


def _load_note_file(path: Path) -> tuple[str, str] | None:
    """读单个 note 文件 → (fm_json, body)；坏文件返回 None（与文件扫描跳过语义一致）。"""
    from memory.governance import MemorySchemaError
    from memory.memdir import split_frontmatter

    try:
        fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, MemorySchemaError, UnicodeDecodeError):
        return None
    return json.dumps(fm, ensure_ascii=False, sort_keys=True), body


def _load_rollout_file(path: Path) -> tuple[str] | None:
    try:
        return (path.read_text(encoding="utf-8"),)
    except (OSError, UnicodeDecodeError):
        return None


def load_notes_cached(domain: str):
    """A4：签名缓存版 load_notes。返回 MemoryNote 列表（与文件扫描逐字节等价）。

    任何 sqlite 异常向上抛出，由调用方（memdir.load_notes）fail-open 回退。
    """
    from memory.governance import parse_and_validate
    from memory.memdir import memdir_root

    topics = memdir_root(domain) / "topics"
    _sync_table(domain, "notes", topics, loader=_load_note_file)
    out = []
    with _connect(domain) as conn:
        cur = conn.execute(
            "SELECT path, fm_json, body FROM notes WHERE domain = ? ORDER BY path",
            (domain,),
        )
        for _path, fm_json, body in cur.fetchall():
            try:
                fm = json.loads(fm_json)
            except json.JSONDecodeError:
                continue
            try:
                out.append(parse_and_validate(fm, body))
            except Exception:  # noqa: BLE001 — 坏行与文件扫描跳过语义一致
                continue
    return out


def load_rollouts_cached(domain: str) -> dict[str, str]:
    """A4：签名缓存版 rollout 原文表 {文件名: raw}。sqlite 异常向上抛。"""
    from memory.memdir import memdir_root

    directory = memdir_root(domain) / "rollout_summaries"
    _sync_table(domain, "rollouts", directory, loader=_load_rollout_file)
    out: dict[str, str] = {}
    with _connect(domain) as conn:
        cur = conn.execute(
            "SELECT path, raw FROM rollouts WHERE domain = ? ORDER BY path", (domain,)
        )
        for name, raw in cur.fetchall():
            out[str(name)] = str(raw)
    return out


def upsert_note_file(domain: str, path: Path) -> None:
    """write-through：write_note 落盘后立即同步单文件（尽力而为，失败静默）。"""
    try:
        _sync_table(domain, "notes", path.parent, loader=_load_note_file)
    except Exception:  # noqa: BLE001 — write-through 不阻塞写路径
        pass


def upsert_rollout_file(domain: str, path: Path) -> None:
    """write-through：rollout 归档落盘后立即同步单文件（尽力而为）。"""
    try:
        _sync_table(domain, "rollouts", path.parent, loader=_load_rollout_file)
    except Exception:  # noqa: BLE001
        pass


def rebuild(domain: str) -> int:
    """全量重建（丢弃签名，强制重读全部文件）；返回重建的 note 条数。"""
    try:
        with _connect(domain) as conn:
            conn.execute("DELETE FROM notes WHERE domain = ?", (domain,))
            conn.execute("DELETE FROM rollouts WHERE domain = ?", (domain,))
    except Exception:  # noqa: BLE001
        return 0
    try:
        load_notes_cached(domain)
        return 1
    except Exception:  # noqa: BLE001
        return 0


# --------------------------------------------------------------------------- #
# fragments（A2 retrieve 还原）
# --------------------------------------------------------------------------- #

def store_fragments(session_id: str, rows: list[dict]) -> int:
    """入库一批压缩碎片：``{msg_index, kind, seq, text}``；返回实际入库条数。

    超限截断（FRAGMENT_TEXT_CAP）+ 总量封顶（FRAGMENT_ROW_CAP）；失败静默（还原
    是增强项，绝不阻塞压缩热路径）。
    """
    sid = (session_id or "").strip()
    if not sid or not rows:
        return 0
    stored = 0
    try:
        with _connect(_domain_for_sessions()) as conn:
            for row in rows[:FRAGMENT_ROW_CAP]:
                try:
                    idx = int(row.get("msg_index") or 0)
                    kind = str(row.get("kind") or "msg")
                    seq = int(row.get("seq") or 0)
                    text = str(row.get("text") or "")[:FRAGMENT_TEXT_CAP]
                except (TypeError, ValueError):
                    continue
                if not text.strip():
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO fragments(session_id, msg_index, kind, seq, text, sha, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (sid, idx, kind, seq, text, _sha(text), _now_iso()),
                )
                stored += 1
    except Exception:  # noqa: BLE001
        return stored
    return stored


def get_fragments(session_id: str, msg_index: int, kind: str | None = None) -> list[dict]:
    """按 ``notes:msg:<i>``（可选 ``:<kind>``）取回碎片；失败/无记录返回空。"""
    sid = (session_id or "").strip()
    if not sid:
        return []
    try:
        sql = (
            "SELECT kind, seq, text FROM fragments"
            " WHERE session_id = ? AND msg_index = ?"
        )
        params: list[Any] = [sid, int(msg_index)]
        if kind:
            sql += " AND kind = ?"
            params.append(str(kind))
        sql += " ORDER BY kind, seq"
        with _connect(_domain_for_sessions()) as conn:
            return [
                {"kind": k, "seq": s, "text": t} for k, s, t in conn.execute(sql, params)
            ]
    except Exception:  # noqa: BLE001
        return []


def _domain_for_sessions() -> str:
    """fragments/edges 的宿主域：跟随当前工作区 memdir（与 L4 同域）。"""
    try:
        from engine.workspace_context import get_cwd
        from memory.memdir import workspace_id

        return workspace_id(get_cwd())
    except Exception:  # noqa: BLE001 — 离线/测试环境回退固定域
        return "offline"


# --------------------------------------------------------------------------- #
# edges（C1 地基：因果链，本轮只建表+写入）
# --------------------------------------------------------------------------- #

def add_edges(session_id: str, rows: list[dict]) -> int:
    """入库因果边 ``{from_msg, to_msg, kind}``（tool_use→tool_result 等）。"""
    sid = (session_id or "").strip()
    if not sid or not rows:
        return 0
    added = 0
    try:
        with _connect(_domain_for_sessions()) as conn:
            for row in rows:
                try:
                    a = int(row.get("from_msg") or 0)
                    b = int(row.get("to_msg") or 0)
                    kind = str(row.get("kind") or "ref")
                except (TypeError, ValueError):
                    continue
                if a < 0 or b < 0 or a == b:
                    continue  # msg_index 从 0 起，0 是合法边端点
                conn.execute(
                    "INSERT OR IGNORE INTO edges(session_id, from_msg, to_msg, kind, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (sid, a, b, kind, _now_iso()),
                )
                added += 1
    except Exception:  # noqa: BLE001
        return added
    return added


def edges_for(session_id: str, msg_index: int) -> list[dict]:
    """取某消息的因果邻接（入边+出边），供未来 DAG 钻取。"""
    sid = (session_id or "").strip()
    if not sid:
        return []
    try:
        with _connect(_domain_for_sessions()) as conn:
            cur = conn.execute(
                "SELECT from_msg, to_msg, kind FROM edges"
                " WHERE session_id = ? AND (from_msg = ? OR to_msg = ?)"
                " ORDER BY from_msg, to_msg",
                (sid, int(msg_index), int(msg_index)),
            )
            return [
                {"from_msg": a, "to_msg": b, "kind": k} for a, b, k in cur.fetchall()
            ]
    except Exception:  # noqa: BLE001
        return []
