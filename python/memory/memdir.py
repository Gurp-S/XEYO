"""L4 长期记忆：workspace memdir（MEMORY.md + topics）。

~/.xeyo/memory/{workspace_id}/
  workspace.json  MEMORY.md  topics/*.md  tombstones.jsonl
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from memory.governance import (
    ALLOWED_TYPES,
    MemoryNote,
    MemorySchemaError,
    Tombstone,
    note_to_frontmatter,
    parse_and_validate,
    today_iso,
)
from memory.instruction import xeyo_home

INDEX_MAX_LINES = 200
INDEX_MAX_BYTES = 25_000
_SLUG_RE = re.compile(r"[^a-z0-9]+")
USER_MEMDIR_ID = "user"

# P1-2 保留期剪枝（prune_stage1_outputs_for_retention）：
# 只剪掉「非 active + 超保留期」的死 note 文件，绝不触碰 active 事实。
ENV_RETENTION_DAYS = "XEYO_MEMORY_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 7.0


def retention_days() -> float:
	"""记忆保留期（天）；默认 7（同 spill.py）。<=0 表示不剪枝。"""
	try:
		return float(os.environ.get(ENV_RETENTION_DAYS, "").strip() or DEFAULT_RETENTION_DAYS)
	except (TypeError, ValueError):
		return DEFAULT_RETENTION_DAYS


def prune_dead_notes(wsid: str, *, now: float | None = None) -> int:
	"""删除「非 active 且超保留期」的 topics 文件；返回删除数。

	- 只删 status in {superseded, deleted}、且 mtime 超保留期的文件；
	- 保留期内或 active 的绝不动（天量死文件也不冒进）；
	- 尽力而为，文件被占用/缺失跳过；不抛（NightShift 后台路径）。
	"""
	days = retention_days()
	if days <= 0:
		return 0
	root = memdir_root(wsid)
	topics = root / "topics"
	if not topics.is_dir():
		return 0
	cutoff = (now if now is not None else time.time()) - days * 86400.0
	removed = 0
	for path in topics.glob("*.md"):
		try:
			fm, _body = split_frontmatter(path.read_text(encoding="utf-8"))
		except (OSError, UnicodeError, MemorySchemaError):
			continue
		status = str(fm.get("status") or "active")
		if status == "active":
			continue
		try:
			if path.stat().st_mtime < cutoff:
				path.unlink()
				removed += 1
		except OSError:
			continue
	return removed


def workspace_id(canonical_path: str) -> str:
    """由规范化工作区路径生成稳定 workspace_id；复制目录必须得到新 id"""
    try:
        p = str(Path(canonical_path).expanduser().resolve())
    except OSError:
        p = os.path.abspath(os.path.expanduser(canonical_path or "."))
    digest = hashlib.sha256(p.encode("utf-8")).hexdigest()[:16]
    slug = _SLUG_RE.sub("_", Path(p).name.lower()).strip("_")[:40] or "ws"
    return f"{slug}_{digest}"




def workspace_path(wsid: str) -> str:
    """从 workspace.json 读 canonical_path；缺失/损坏返回 ''（P3 diff 佐证用）。"""
    path = memdir_root(wsid) / "workspace.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("canonical_path") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def resolve_memdir_id(wsid: str, *, scope: str = "workspace") -> str:
    """按 scope 选择落盘域：user → 全局 user；其余 → 工作区 wsid。"""
    if (scope or "").strip() == "user":
        return USER_MEMDIR_ID
    return wsid


def memdir_root(wsid: str) -> Path:
    """返回该记忆域根目录（~/.xeyo/memory/{workspace_id|user}/）"""
    override = os.environ.get("XEYO_MEMORY_DIR", "").strip()
    if override:
        base = Path(override).expanduser()
    else:
        base = xeyo_home() / "memory"
    return base / wsid


def ensure_layout(wsid: str, *, canonical_path: str = "") -> Path:
    """创建 memdir 骨架（topics / tombstones / workspace.json）。"""
    root = memdir_root(wsid)
    (root / "topics").mkdir(parents=True, exist_ok=True)
    ws = root / "workspace.json"
    if not ws.is_file():
        payload = {
            "workspace_id": wsid,
            "canonical_path": canonical_path,
            "created_at": today_iso(),
        }
        ws.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    idx = root / "MEMORY.md"
    if not idx.is_file():
        idx.write_text("# Memory index\n", encoding="utf-8")
    ts = root / "tombstones.jsonl"
    if not ts.is_file():
        ts.write_text("", encoding="utf-8")
    return root


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """拆 YAML-ish frontmatter 与正文。"""
    raw = text or ""
    if not raw.startswith("---"):
        raise MemorySchemaError("missing frontmatter")
    rest = raw[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end < 0:
        raise MemorySchemaError("unterminated frontmatter")
    fm_text = rest[:end]
    body = rest[end + 4 :].lstrip("\n")
    return _parse_fm(fm_text), body


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s in ("", "null", "None", "~"):
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s.startswith('"') and s.endswith('"'):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s[1:-1]
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return s
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def _parse_fm(text: str) -> dict[str, Any]:
    """极简 frontmatter：key: value，两级缩进 map/list。"""
    data: dict[str, Any] = {}
    map_key: str | None = None
    list_key: str | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        if raw_line.startswith("  - "):
            if list_key is None:
                continue
            items = data.get(list_key)
            if not isinstance(items, list):
                if items != {}:
                    continue
                items = data[list_key] = []
            items.append(_parse_scalar(raw_line[4:]))
            continue
        if raw_line.startswith("  ") and map_key:
            line = raw_line.strip()
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            nested = data.setdefault(map_key, {})
            if not isinstance(nested, dict):
                nested = {}
                data[map_key] = nested
            nested[k.strip()] = _parse_scalar(v)
            continue
        if ":" not in raw_line:
            continue
        key, val = raw_line.split(":", 1)
        key = key.strip()
        val = val.strip()
        map_key = None
        list_key = None
        if val == "":
            data[key] = {}
            map_key = key
            list_key = key
            continue
        data[key] = _parse_scalar(val)
        if isinstance(data[key], list):
            list_key = key
        if isinstance(data[key], dict):
            map_key = key
    return data


def dump_frontmatter(data: dict[str, Any]) -> str:
    """把字典写成 --- 包裹的简单 frontmatter。"""
    lines = ["---"]
    for key, val in data.items():
        if isinstance(val, dict):
            lines.append(f"{key}:")
            for nk, nv in val.items():
                lines.append(f"  {nk}: {json.dumps(nv, ensure_ascii=False)}")
        elif isinstance(val, list):
            if not val:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in val:
                    lines.append(f"  - {json.dumps(item, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {json.dumps(val, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def topic_filename(note: MemoryNote) -> str:
    """topics/ 下的稳定文件名。"""
    identity = hashlib.sha256(note.id.encode("utf-8")).hexdigest()
    return f"{note.type}-{identity}.md"


def note_topics_path(note: MemoryNote, wsid: str) -> Path:
    """该 note 在 topics/ 下的磁盘路径。"""
    topics = memdir_root(wsid) / "topics"
    canonical = topics / topic_filename(note)
    if canonical.is_file():
        return canonical
    for candidate in sorted(topics.glob("*.md")):
        try:
            fm, _ = split_frontmatter(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, MemorySchemaError):
            continue
        if str(fm.get("id") or "").strip() == note.id:
            return candidate
    return canonical


def note_location(note: MemoryNote, wsid: str) -> tuple[str, int | None, int | None]:
    """note 正文的引用定位：返回 (相对路径, 起始行, 结束行)（1-based 闭区间）。

    行号取 frontmatter 结束后的正文首/末非空行；文件缺失或 frontmatter 不规整
    时行号返回 None（只给路径）。供 citation 检索锚点使用，纯读无副作用。
    """
    path = note_topics_path(note, wsid)
    rel = f"notes/topics/{path.name}"
    if not path.is_file():
        return rel, None, None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rel, None, None
    close = None
    if lines and lines[0].lstrip().startswith("---"):
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                close = idx
                break
    if close is None:
        return rel, None, None
    start = close + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines):
        return rel, None, None
    end = len(lines) - 1
    while end > start and not lines[end].strip():
        end -= 1
    return rel, start + 1, end + 1


def index_line(note: MemoryNote, *, wsid: str | None = None) -> str:
    """MEMORY.md 一行导航（无叙事）。"""
    filename = topic_filename(note) if wsid is None else note_topics_path(note, wsid).name
    rel = f"topics/{filename}"
    title = (note.title or note.id).replace("\n", " ").strip()
    return f"[{note.type}] {title} → {rel}"


def rewrite_index(notes: list[MemoryNote], *, wsid: str) -> None:
    """只写导航行 [type] 标题 → topics/xxx.md；禁止叙事；仅 mutation 成功或 NightShift 时调用"""
    root = ensure_layout(wsid)
    lines = ["# Memory index"]
    for note in notes:
        if note.status != "active" or not note.indexable or note.type not in ALLOWED_TYPES:
            continue
        lines.append(index_line(note, wsid=wsid))
        if len(lines) - 1 >= INDEX_MAX_LINES:
            break
    text = "\n".join(lines) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > INDEX_MAX_BYTES:
        text = encoded[:INDEX_MAX_BYTES].decode("utf-8", errors="ignore")
        if not text.endswith("\n"):
            text += "\n"
    path = root / "MEMORY.md"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_index_text(wsid: str) -> str:
    """热路径只读 MEMORY.md；两次非 mutation 的 submit 之间字节必须不变"""
    path = memdir_root(wsid) / "MEMORY.md"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_notes(wsid: str) -> list[MemoryNote]:
    """读取 topics/*.md 为 Note 列表；坏文件跳过。

    A4（**已固化开启**，原 ``XEYO_MEMORY_SQLITE_INDEX`` 键已删）：走 sqlite 签名缓存
    （按 (mtime,size) 只重读变化的文件，查询不再全量解析）；**任何异常 fail-open
    回退文件扫描**——P0 词法召回行为永不回归（缓存内容与逐文件解析逐字节等价）。
    """
    try:
        from memory import memindex

        if memindex.sqlite_index_enabled():
            cached = memindex.load_notes_cached(wsid)
            latest: dict[str, MemoryNote] = {}
            for note in cached:
                previous = latest.get(note.id)
                if previous is None or note.updated_at >= previous.updated_at:
                    latest[note.id] = note
            return list(latest.values())
    except Exception:  # noqa: BLE001 — fail-open 回退文件扫描
        pass
    topics = memdir_root(wsid) / "topics"
    if not topics.is_dir():
        return []
    notes_by_id: dict[str, tuple[bool, MemoryNote]] = {}
    for path in sorted(topics.glob("*.md")):
        try:
            fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
            note = parse_and_validate(fm, body)
        except (OSError, UnicodeError, MemorySchemaError):
            continue
        canonical = path.name == topic_filename(note)
        previous = notes_by_id.get(note.id)
        if (
            previous is None
            or (canonical and not previous[0])
            or (canonical == previous[0] and note.updated_at > previous[1].updated_at)
        ):
            notes_by_id[note.id] = (canonical, note)
    return [note for _, note in notes_by_id.values()]


def write_note(note: MemoryNote, *, wsid: str) -> Path:
    """把 Note 写入 topics/，不改索引（调用方成功后 rewrite_index）。

    ``scope=user`` 路由到 ``~/.xeyo/memory/user/``，与工作区域隔离。
    """
    from memory.note_access import identity_lock

    target = resolve_memdir_id(wsid, scope=note.scope)
    with identity_lock(target, note.id):
        return _write_note_locked(note, target=target)


def _write_note_locked(note: MemoryNote, *, target: str, migrate: bool = True) -> Path:
    root = ensure_layout(target)
    path = root / "topics" / topic_filename(note)
    body = dump_frontmatter(note_to_frontmatter(note)) + "\n" + note.content.strip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy_paths: list[Path] = []
    for candidate in (path.parent.glob("*.md") if migrate else ()):
        if candidate == path:
            continue
        try:
            fm, _ = split_frontmatter(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, MemorySchemaError):
            continue
        if str(fm.get("id") or "").strip() == note.id:
            legacy_paths.append(candidate)
    if path.exists():
        try:
            fm, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, MemorySchemaError) as exc:
            raise MemorySchemaError("topic_identity_unreadable") from exc
        if str(fm.get("id") or "").strip() != note.id:
            raise MemorySchemaError("topic_identity_conflict")
    tmp = path.with_suffix(".md.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    try:
        published, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, MemorySchemaError) as exc:
        raise MemorySchemaError("topic_identity_unreadable") from exc
    if str(published.get("id") or "").strip() != note.id:
        raise MemorySchemaError("topic_identity_conflict")
    if legacy_paths:
        index_path = root / "MEMORY.md"
        index_text = index_path.read_text(encoding="utf-8")
        migrated_index = index_text
        for legacy in legacy_paths:
            migrated_index = migrated_index.replace(
                f"topics/{legacy.name}", f"topics/{path.name}"
            )
        if migrated_index != index_text:
            index_tmp = index_path.with_name(index_path.name + ".migrate.tmp")
            with index_tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(migrated_index)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(index_tmp, index_path)
    # Publish the identity-addressed file before retiring any legacy title path.
    # A failed write therefore leaves the prior source available.
    for legacy in legacy_paths:
        try:
            legacy.unlink()
        except OSError:
            pass
    # A4 write-through：落盘即同步进 sqlite 派生索引（尽力而为，失败静默）
    try:
        from memory import memindex

        memindex.upsert_note_file(target, path)
    except Exception:  # noqa: BLE001 — 写穿透不阻塞写路径
        pass
    return path


def find_note(wsid: str, note_id: str) -> MemoryNote | None:
    """按 id 找一条 Note（先工作区，再 user 域）。"""
    from memory.note_access import find_in_domain

    note = find_in_domain(wsid, note_id)
    if note is None and wsid != USER_MEMDIR_ID:
        note = find_in_domain(USER_MEMDIR_ID, note_id)
    return note


def touch_last_used(note: MemoryNote, *, wsid: str) -> MemoryNote:
    """Re-read under the writer lock; unchanged dates do not publish a new file."""
    from dataclasses import replace
    from memory.note_access import find_in_domain, identity_lock

    target = resolve_memdir_id(wsid, scope=note.scope)
    with identity_lock(target, note.id):
        current = find_in_domain(target, note.id)
        if current is None or current.status != "active":
            return note
        today = today_iso()
        if current.last_used_at == today:
            return current
        updated = replace(current, last_used_at=today, updated_at=current.updated_at)
        canonical = memdir_root(target) / "topics" / topic_filename(current)
        _write_note_locked(updated, target=target, migrate=not canonical.is_file())
        return updated


def load_notes_for_search(wsid: str, *, scope: str = "") -> list[MemoryNote]:
    """搜索用：默认合并工作区 + user；scope=user 只读用户域。"""
    if scope == "user":
        return load_notes(USER_MEMDIR_ID)
    notes = list(load_notes(wsid))
    if wsid != USER_MEMDIR_ID:
        seen = {n.id for n in notes}
        for n in load_notes(USER_MEMDIR_ID):
            if n.id not in seen:
                notes.append(n)
    if scope and scope != "all":
        notes = [n for n in notes if n.scope == scope]
    return notes


def load_tombstones(wsid: str) -> list[Tombstone]:
    """读取 tombstones.jsonl。"""
    path = memdir_root(wsid) / "tombstones.jsonl"
    if not path.is_file():
        return []
    out: list[Tombstone] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict) and row.get("id"):
                out.append(
                    Tombstone(
                        id=str(row["id"]),
                        deleted_at=str(row.get("deleted_at") or ""),
                        reason=str(row.get("reason") or ""),
                    )
                )
    except (OSError, json.JSONDecodeError):
        return out
    return out


def append_tombstone(stone: Tombstone, *, wsid: str) -> None:
    """追加一条墓碑。"""
    root = ensure_layout(wsid)
    path = root / "tombstones.jsonl"
    row = json.dumps(
        {"id": stone.id, "deleted_at": stone.deleted_at, "reason": stone.reason},
        ensure_ascii=False,
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(row + "\n")


def is_under_memdir(path: str, *, wsid: str | None = None, cwd: str | None = None) -> bool:
    """路径是否落在（本工作区的）memdir 内。"""
    try:
        abs_path = str(Path(path).expanduser().resolve())
    except OSError:
        abs_path = os.path.abspath(path)
    if wsid:
        roots = [memdir_root(wsid)]
    elif cwd:
        roots = [memdir_root(workspace_id(cwd))]
    else:
        roots = [xeyo_home() / "memory"]
        override = os.environ.get("XEYO_MEMORY_DIR", "").strip()
        if override:
            roots.append(Path(override).expanduser())
    for root in roots:
        try:
            base = str(root.resolve())
        except OSError:
            base = str(root)
        prefix = os.path.join(base, "")
        if abs_path == base or abs_path.startswith(prefix):
            return True
    return False


def candidates_path(wsid: str) -> Path:
    """Candidate JSONL 路径。"""
    return memdir_root(wsid) / "candidates.jsonl"
