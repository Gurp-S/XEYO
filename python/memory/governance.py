"""L4 治理：MemoryNote schema、冲突、tombstone、晋升闸。无 I/O。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

ALLOWED_TYPES = {"user", "feedback", "project", "reference"}
ALLOWED_STATUS = {"active", "superseded", "deleted"}
ALLOWED_SCOPE = {"user", "workspace", "project", "task"}
ALLOWED_SOURCE_KIND = {"user", "agent", "inference", "nightshift"}
# Agent / 主会话收割证据：允许晋升，但置信度封顶（见 promotion_confidence）
AGENT_HARVEST_EVIDENCE = frozenset(
	{"subagent_marker", "main_harvest", "agent_harvest"}
)
AGENT_PROMOTE_CONFIDENCE = 0.6


class MemorySchemaError(ValueError):
    """frontmatter 不合 schema，不得当 active。"""


@dataclass(frozen=True)
class MemoryNote:
    """一条长期记忆（Knowledge Truth）；缺必填字段不得当 active"""

    id: str  # 稳定 id（如 mem_01J…）
    type: str  # user | feedback | project | reference
    content: str  # 事实正文（不含索引叙事）
    source: dict  # 溯源：kind / session_id / message_id
    confidence: float  # 1.0 用户确认 / ≤0.6 推断
    status: str  # active | superseded | deleted
    scope: str  # user | workspace | project | task
    applies_to: list  # 路径/工作区等适用范围，用于冲突分流
    created_at: str  # 首次写入日
    updated_at: str  # 最近改字节日
    last_confirmed_at: str  # 最近一次被确认日（消解冲突用）
    last_used_at: str | None  # 最近一次被检索/引用；可空
    expires_at: str | None  # 过期日；空表示不过期
    supersedes: str | None  # 本条替换的旧 Note id；无则空
    title: str = ""  # 索引一行标题
    indexable: bool = True  # 四类之外降级后不得进 MEMORY.md


@dataclass(frozen=True)
class Tombstone:
    """已遗忘条目的墓碑；NightShift 禁止按旧 JSONL 复活"""

    id: str  # 被删 Note 的 id
    deleted_at: str  # 删除日
    reason: str  # 如 user_request


@dataclass
class MemoryCandidate:
    """待验证候选；未过闸不得写入 topics / 不得进 MEMORY.md"""

    content: str  # 候选陈述
    source: dict  # 来自哪次会话/消息
    evidence: list[str] = field(default_factory=list)  # 用户确认/事实/多会话证据


def new_note_id() -> str:
    """生成稳定 Note id。"""
    return "mem_" + uuid4().hex[:16]


def today_iso() -> str:
    """今天的 ISO 日期。"""
    return date.today().isoformat()


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _as_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError) as exc:
        raise MemorySchemaError("confidence must be a number") from exc


def parse_and_validate(frontmatter: dict, body: str) -> MemoryNote:
    """把 frontmatter+正文校验成 MemoryNote；缺 source/confidence/status 则拒绝"""
    if not isinstance(frontmatter, dict):
        raise MemorySchemaError("frontmatter must be a mapping")
    note_type_raw = _as_str(frontmatter.get("type"))
    indexable = note_type_raw in ALLOWED_TYPES
    note_type = note_type_raw if indexable else "untyped"
    source = frontmatter.get("source")
    if not isinstance(source, dict) or not _as_str(source.get("kind")):
        raise MemorySchemaError("source.kind is required")
    if "confidence" not in frontmatter:
        raise MemorySchemaError("confidence is required")
    if "status" not in frontmatter:
        raise MemorySchemaError("status is required")
    status = _as_str(frontmatter.get("status"))
    if status not in ALLOWED_STATUS:
        raise MemorySchemaError("status must be active|superseded|deleted")
    scope = _as_str(frontmatter.get("scope") or "workspace")
    if scope not in ALLOWED_SCOPE:
        raise MemorySchemaError("scope must be user|workspace|project|task")
    applies = frontmatter.get("applies_to") or []
    if not isinstance(applies, list):
        raise MemorySchemaError("applies_to must be a list")
    content = (body or "").strip() or _as_str(frontmatter.get("content"))
    if not content:
        raise MemorySchemaError("content is required")
    title = _as_str(frontmatter.get("title")) or content.splitlines()[0][:80]
    note_id = _as_str(frontmatter.get("id")) or new_note_id()
    created = _as_str(frontmatter.get("created_at")) or today_iso()
    updated = _as_str(frontmatter.get("updated_at")) or created
    confirmed = _as_str(frontmatter.get("last_confirmed_at")) or created
    last_used = frontmatter.get("last_used_at")
    expires = frontmatter.get("expires_at")
    supersedes = frontmatter.get("supersedes")
    return MemoryNote(
        id=note_id,
        type=note_type,
        content=content,
        source={
            "kind": _as_str(source.get("kind")),
            "session_id": _as_str(source.get("session_id")),
            "message_id": _as_str(source.get("message_id")),
        },
        confidence=_as_float(frontmatter.get("confidence")),
        status=status,
        scope=scope,
        applies_to=list(applies),
        created_at=created,
        updated_at=updated,
        last_confirmed_at=confirmed,
        last_used_at=_as_str(last_used) or None,
        expires_at=_as_str(expires) or None,
        supersedes=_as_str(supersedes) or None,
        title=title,
        indexable=indexable,
    )


def can_promote(candidate: MemoryCandidate) -> bool:
	"""是否允许晋升为 active。

	闸门：用户确认 / 可核对事实 / 多 session 无冲突 / 控制面 /
	agent|主会话收割标记（置信度封顶，见 ``promotion_confidence``）/
	工作区改动 diff 佐证（``verified_by_diff``：仅 NightShift 对照真实 git 改动
	打标后生效，见 memory.workspace_diff —— P3，纯证据通道不放开既有门禁）。
	禁止仅因 repeat* 重复出现。
	"""
	kind = ""
	if isinstance(candidate.source, dict):
		kind = str(candidate.source.get("kind") or "")
	evidence = list(candidate.evidence or [])
	if kind == "user":
		return True
	if "user_confirm" in evidence or "control_plane" in evidence:
		return True
	if "verified_fact" in evidence:
		return True
	# P3：改动 diff 佐证 —— 先由 NightShift 对照真实工作区改动打标，这里才放行。
	if "verified_by_diff" in evidence:
		return True
	if any(e in AGENT_HARVEST_EVIDENCE for e in evidence):
		return True
	if kind == "agent" and any(
		e in AGENT_HARVEST_EVIDENCE or e.startswith("session:") for e in evidence
	):
		return True
	sessions = {e for e in evidence if e.startswith("session:")}
	if len(sessions) >= 2 and "no_conflict" in evidence:
		return True
	# 仅重复出现不得晋升
	if evidence and all(e.startswith("repeat") for e in evidence):
		return False
	return False


def promotion_confidence(candidate: MemoryCandidate) -> float:
	"""晋升写入时的置信度：用户/确认=1.0；agent 收割封顶 0.6；diff 佐证 0.85。"""
	kind = ""
	if isinstance(candidate.source, dict):
		kind = str(candidate.source.get("kind") or "")
	evidence = list(candidate.evidence or [])
	if kind == "user" or "user_confirm" in evidence or "control_plane" in evidence:
		return 1.0
	if "verified_fact" in evidence or "verified_by_diff" in evidence:
		return 0.85
	if any(e in AGENT_HARVEST_EVIDENCE for e in evidence) or kind in {
		"agent",
		"inference",
		"nightshift",
	}:
		return AGENT_PROMOTE_CONFIDENCE
	return AGENT_PROMOTE_CONFIDENCE


def _applies_key(note: MemoryNote) -> tuple:
    """把 applies_to 收成可哈希键，用于冲突分流。"""
    parts: list[str] = []
    for item in note.applies_to:
        if isinstance(item, dict):
            parts.append(repr(sorted(item.items())))
        else:
            parts.append(str(item))
    return (note.scope, tuple(parts))


def resolve_conflict(old: MemoryNote, new: MemoryNote) -> str:
    """先比 scope/applies_to；不冲突返回 coexist。

    只把「同一主题（type+title 相同）或新笔记显式 supersedes 旧 id」当作替换：
    若只看 scope/applies_to，任何同 scope 新笔记都会吞掉其它类型/标题的旧笔记，
    导致已记住的事实从索引/搜索里静默消失。推断仍不得覆盖用户确认（keep_old）。
    """
    if _applies_key(old) != _applies_key(new):
        return "coexist"
    old_user = old.source.get("kind") == "user" and old.confidence >= 1.0
    new_infer = new.source.get("kind") in {"inference", "nightshift", "agent"} and new.confidence < 1.0
    if old_user and new_infer:
        return "keep_old"
    same_topic = (old.type, (old.title or "").strip()) == (
        new.type,
        (new.title or "").strip(),
    )
    explicit = str(new.supersedes or "") == old.id
    if same_topic or explicit:
        return "supersede"
    return "coexist"


def forget(note_id: str, *, reason: str = "user_request") -> Tombstone:
    """将 Note 标 deleted 并生成 tombstone，供索引删除与 NightShift 遵守"""
    return Tombstone(id=note_id, deleted_at=today_iso(), reason=reason)


def may_resurrect(note_id: str, tombstones: list[Tombstone]) -> bool:
    """是否允许把已遗忘 id 写回 active；永远 False（NightShift 硬禁止）"""
    _ = note_id, tombstones
    return False


def note_to_frontmatter(note: MemoryNote) -> dict[str, Any]:
    """把 Note 编成可写入 topics 的 frontmatter 字典。"""
    return {
        "id": note.id,
        "type": note.type,
        "title": note.title,
        "source": dict(note.source),
        "confidence": note.confidence,
        "status": note.status,
        "scope": note.scope,
        "applies_to": list(note.applies_to),
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "last_confirmed_at": note.last_confirmed_at,
        "last_used_at": note.last_used_at,
        "expires_at": note.expires_at,
        "supersedes": note.supersedes,
    }
