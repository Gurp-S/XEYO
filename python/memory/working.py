"""L3 工作记忆：WorkingSnapshot sidecar。

本文件只做机器状态，不写给模型看的叙事。

flowchart LR
  Init[QueryEngine 启动] --> Hyd[hydrate]
  Hyd --> Loop[每轮 query_loop]
  Loop --> Shot[note_shot]
  Loop -->|a*=C2| C2[note_c2]
  Shot --> Flush[submit 结束 flush]
  C2 --> Flush
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class CompactCheckpoint:
    """C2 compact checkpoint（落盘在 ``<id>.working.json``）。

    投影锚点（anchor_*）+ 窗口链（window_chain）+ 首压摘要（anchor_summary）。
    resume 时由 ``_from_dict`` 用它重建投影：把 cursor/frozen 对齐到锚点、
    并回填冻结的 ``c2_summary_text``，保证「set checkpoint → flush → hydrate →
    projection 一致」。
    """

    version: int = 1  # checkpoint 格式版本，缺省 1
    anchor_cursor: int = 0  # 投影锚点：首压时冻结的 compact_cursor
    anchor_frozen_until: int = 0  # 投影锚点：首压时的 c1_frozen_until
    anchor_summary: str = ""  # 首压摘要文本（KV 前缀冻结，必为 c2_summary_text 的副本）
    # 窗口链：每次 C2/append-only 扩展追加一条 {cursor, frozen_until, summary_fp}
    window_chain: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProjectionDigest:
    """投影 X 的可重入计量信息（**不存全文**，P1 缺失2）。

    只持久化重建 Ĥ/LCP 所需的最小计量：冻结前缀的哈希 + 各段 token 长度。
    这样杀进程重启后，``decide`` 仍能算出 ``lcp_keep``（= 冻结前缀长度），而无需
    重放整段投影或把全文写进 sidecar。``tail_len = total_len - frozen_len``。

    若上次投影从未建立（如首轮冷启动），``frozen_len=0``，调用方保守取 0。
    """

    prefix_hash: str = ""  # 冻结前缀（P = p_s + p_c）文本的 sha256
    total_len: int = 0  # 完整投影 X 的 token 长度
    frozen_len: int = 0  # 冻结前缀 P 的 token 长度（= Projected.p_end）
    tail_len: int = 0  # total_len - frozen_len（M+Tk+Tnow 段）


@dataclass
class WorkingSnapshot:
    """会话的工作状态（压缩游标、调用统计、辅助数据）"""

    session_id: str = ""  # 与 JSONL / sidecar 文件名一致
    agent_id: str = "main"  # 当前智能体标识
    compact_cursor: int = 0  # 已压实的历史消息索引（只增不减）
    c1_frozen_until: int = 0  # C1 冻结边界：此索引之前的 tool_result 一律占位，不再回退
    c2_summary_text: str = ""  # C2 摘要文本（首次压缩时冻结，保证后续请求字节稳定）
    turns_since_c2: int = 0  # 自上次 C2 压缩后的对话轮次
    last_model_call_at: datetime | None = None  # 最近一次模型调用时间
    last_cache_hit_tokens: int = 0  # 最近请求的缓存命中 token 数
    last_prompt_tokens: int = 0  # 最近请求的 prompt token 总数
    last_x_sim: str = ""  # 上一轮送模型的 simulator 格式投影 X，用于热路径 Ĥ 预测
    last_action: str = ""  # 上一枪实际发送的动作：project / keep / C1 / C2
    last_x_sent: str = ""  # 上一枪实际发送投影的规范化 JSON，供下一枪 LCP / Ĥ 预测
    speculation: list[str] = field(default_factory=list)  # 本回合假说，默认不晋升 L4
    loaded_nested_instruction_paths: list[str] = field(default_factory=list)  # 已加载的嵌套指令路径
    # T17：嵌套指令 path → 内容 SHA-1（trim 后），驱动更新/移除墓碑 diff。
    nested_hashes: dict[str, str] = field(default_factory=dict)
    todos: list[dict[str, str]] = field(default_factory=list)  # TodoStore 序列化，不含权威叙事
    tasks: list[dict[str, Any]] = field(default_factory=list)  # 多Agent任务清单（id/depends_on/scope/required_tools/timeout_s）
    read_file_state: dict[str, dict[str, Any]] = field(default_factory=dict)  # 路径 → mtime/offset，不含文件正文
    session_md_tool_epoch: int = 0  # 上次写 session.md 时的工具调用计数
    # 进程内投影增量缓存（不落盘）：(base_len, frozen, cursor, summary_fp, projection, id_to_name)
    # 跨 submit 复用，避免每次用户消息对全历史 deepcopy。
    proj_cache: tuple[int, int, int, int, list[dict], dict[str, str]] | None = field(
        default=None, repr=False, compare=False
    )
    # C2 compact checkpoint（落盘）：投影锚点 + 窗口链 + 首压摘要（T8）。
    compact_checkpoint: CompactCheckpoint | None = field(
        default=None, repr=False, compare=False
    )
    # C2 LLM 摘要旁路的预取结果（仅内存，不落盘；供 apply_c2_messages 同步消费）。
    _pending_c2_summary: str | None = field(default=None, repr=False, compare=False)
    # T31 跨入口会话与模式 SSOT —— durable 模式记录（log-only + resume 重放）。
    # 请求 contextvar 只是投影；这里存「本会话最后已知模式」，任何入口恢复该
    # 会话时由此重建模式。缺省值即「从未设置/默认」语义，fail-closed。
    agent_mode: str = "agent"  # agent / plan / ask
    output_compact: bool = False  # 输出精简开关
    output_mode: str = ""  # ""=未显式；否则 lite / full / ultra
    code_compact: bool = False  # 写代码精简开关
    code_mode: str = ""  # ""=未显式；否则 lite / full / ultra
    reasoning_tail: bool = False  # 上一轮思考回顾 T_now 注入开关（默认关）
    # P1 缺失1：当前 M 段的信息原子分段（可重入计量，不存全文）。
    # 序列化为 [{kind, weight, text}]，供 Q 按原子计权与审计观察。
    current_atoms: list[dict[str, Any]] = field(default_factory=list)
    # P1 缺失2：上一枪发送投影 X 的可重入计量（不存全文）。重启后 decide 用它算
    # lcp_keep，避免依赖易失的 last_x_sim 全文。随 flush/hydrate 持久化。
    last_projection: ProjectionDigest | None = field(
        default=None, repr=False, compare=False
    )

def _sessions_dir() -> Path:
    """会话 sidecar 目录（与 JSONL 相同，可用 XEYO_SESSIONS_DIR 覆盖）。"""
    override = os.environ.get("XEYO_SESSIONS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".xeyo" / "sessions"


def _safe_name(session_id: str) -> str:
    """会话键 → 稳定文件名。"""
    raw = session_id or "session"
    parts: list[str] = []
    for ch in raw:
        if ch == ":":
            parts.append("__")
        elif ch.isalnum() or ch in "._-":
            parts.append(ch)
        else:
            parts.append("_")
    return "".join(parts).strip("._") or "session"


def path_for(session_id: str) -> Path:
    """返回会话快照的文件路径（~/.xeyo/sessions/{id}.working.json）"""
    return _sessions_dir() / f"{_safe_name(session_id)}.working.json"


def _parse_dt(raw: object) -> datetime | None:
    """把 sidecar 里的 ISO 时间解析成 datetime；坏值当空。"""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _cp_window(cursor: int, frozen_until: int, summary_text: str | None) -> dict[str, Any]:
    """把一次 C2/扩展事件记成窗口链条目。"""
    return {
        "cursor": int(cursor),
        "frozen_until": int(frozen_until),
        "summary_fp": len(summary_text or ""),
    }


def note_compact_checkpoint(
    snap: WorkingSnapshot,
    *,
    cursor: int,
    frozen_until: int,
    summary_text: str | None,
) -> None:
    """首压 C2：建立 compact checkpoint（投影锚点 + 窗口链第一项）。"""
    if not cursor or cursor <= 0:
        return
    cp = snap.compact_checkpoint
    if cp is None:
        cp = CompactCheckpoint(
            anchor_cursor=int(cursor),
            anchor_frozen_until=int(frozen_until),
            anchor_summary=str(summary_text or ""),
        )
        snap.compact_checkpoint = cp
    # 无论新建或已存在：锚点只前进（cursor 只增不减），窗口链追加一条
    cp.anchor_cursor = max(int(cp.anchor_cursor or 0), int(cursor))
    cp.anchor_frozen_until = max(int(cp.anchor_frozen_until or 0), int(frozen_until))
    if not (cp.anchor_summary or "").strip():
        cp.anchor_summary = str(summary_text or "")
    cp.window_chain.append(_cp_window(cursor, frozen_until, summary_text))


def append_compact_window(
    snap: WorkingSnapshot,
    *,
    cursor: int,
    frozen_until: int,
    summary_text: str | None,
) -> None:
    """已压缩态 append-only 扩展：窗口链记一条，锚点同步推进。"""
    if not cursor or cursor <= 0:
        return
    cp = snap.compact_checkpoint
    if cp is None:
        cp = CompactCheckpoint(
            anchor_cursor=int(cursor),
            anchor_frozen_until=int(frozen_until),
            anchor_summary=str(summary_text or ""),
        )
        snap.compact_checkpoint = cp
    else:
        cp.anchor_cursor = max(int(cp.anchor_cursor or 0), int(cursor))
        cp.anchor_frozen_until = max(int(cp.anchor_frozen_until or 0), int(frozen_until))
    cp.window_chain.append(_cp_window(cursor, frozen_until, summary_text))


def _to_dict(snap: WorkingSnapshot) -> dict[str, Any]:
    """把快照编成可 JSON 化的字典。"""
    at = snap.last_model_call_at
    cp = snap.compact_checkpoint
    cp_payload = None
    if cp is not None:
        cp_payload = {
            "version": int(cp.version or 1),
            "anchor_cursor": int(cp.anchor_cursor or 0),
            "anchor_frozen_until": int(cp.anchor_frozen_until or 0),
            "anchor_summary": str(cp.anchor_summary or ""),
            "window_chain": list(cp.window_chain),
        }
    return {
        "session_id": snap.session_id,
        "agent_id": snap.agent_id,
        "compact_cursor": int(snap.compact_cursor),
        "c1_frozen_until": int(snap.c1_frozen_until),
        "c2_summary_text": str(snap.c2_summary_text or ""),
        "compact_checkpoint": cp_payload,
        "turns_since_c2": int(snap.turns_since_c2),
        "last_model_call_at": at.isoformat() if at else None,
        "last_cache_hit_tokens": int(snap.last_cache_hit_tokens),
        "last_prompt_tokens": int(snap.last_prompt_tokens),
        "last_x_sim": str(snap.last_x_sim or ""),
        "last_action": str(snap.last_action or ""),
        "last_x_sent": str(snap.last_x_sent or ""),
        "speculation": list(snap.speculation),
        "loaded_nested_instruction_paths": list(snap.loaded_nested_instruction_paths),
        "nested_hashes": dict(getattr(snap, "nested_hashes", {}) or {}),
        "todos": list(snap.todos),
        "tasks": list(snap.tasks),
        "read_file_state": dict(snap.read_file_state),
        "session_md_tool_epoch": int(snap.session_md_tool_epoch),
        # T31 durable 模式记录（log-only，绝不进模型可见 JSONL/历史）。
        "agent_mode": str(snap.agent_mode or "agent"),
        "output_compact": bool(snap.output_compact),
        "output_mode": str(snap.output_mode or ""),
        "code_compact": bool(snap.code_compact),
        "code_mode": str(snap.code_mode or ""),
        "reasoning_tail": bool(snap.reasoning_tail),
        "current_atoms": list(getattr(snap, "current_atoms", []) or []),
        "last_projection": _projection_to_dict(getattr(snap, "last_projection", None)),
    }


def _projection_to_dict(digest: ProjectionDigest | None) -> dict[str, Any] | None:
    """把 ProjectionDigest 编成可 JSON 化的字典；None 时输出 None。"""
    if digest is None:
        return None
    return {
        "prefix_hash": str(digest.prefix_hash or ""),
        "total_len": int(digest.total_len or 0),
        "frozen_len": int(digest.frozen_len or 0),
        "tail_len": int(digest.tail_len or 0),
    }


def _parse_projection(raw: object) -> ProjectionDigest | None:
    """从字典恢复 ProjectionDigest；坏值/缺失返回 None（调用方保守取 0）。"""
    if not isinstance(raw, dict):
        return None
    try:
        total = max(0, int(raw.get("total_len") or 0))
    except (TypeError, ValueError):
        total = 0
    try:
        frozen = max(0, int(raw.get("frozen_len") or 0))
    except (TypeError, ValueError):
        frozen = 0
    try:
        tail = max(0, int(raw.get("tail_len") or 0))
    except (TypeError, ValueError):
        tail = 0
    return ProjectionDigest(
        prefix_hash=str(raw.get("prefix_hash") or ""),
        total_len=total,
        frozen_len=frozen,
        tail_len=tail,
    )


def _parse_checkpoint(raw: dict[str, Any] | None) -> CompactCheckpoint | None:
    """从字典恢复 CompactCheckpoint；坏值按空。"""
    if not isinstance(raw, dict):
        return None
    try:
        anchor_cursor = max(0, int(raw.get("anchor_cursor") or 0))
    except (TypeError, ValueError):
        anchor_cursor = 0
    try:
        anchor_frozen = max(0, int(raw.get("anchor_frozen_until") or 0))
    except (TypeError, ValueError):
        anchor_frozen = 0
    chain = raw.get("window_chain")
    if not isinstance(chain, list):
        chain = []
    chain = [d for d in chain if isinstance(d, dict)]
    try:
        version = max(1, int(raw.get("version") or 1))
    except (TypeError, ValueError):
        version = 1
    return CompactCheckpoint(
        version=version,
        anchor_cursor=anchor_cursor,
        anchor_frozen_until=anchor_frozen,
        anchor_summary=str(raw.get("anchor_summary") or ""),
        window_chain=[dict(x) for x in chain],
    )


def _from_dict(raw: dict[str, Any], session_id: str) -> WorkingSnapshot:
    """从字典恢复快照；缺字段用默认。

    T8：读回 compact_checkpoint 后做**投影锚点对齐**——resume 时 cursor/frozen
    对齐到锚点、并回填冻结的 c2_summary_text，保证「set checkpoint → flush →
    hydrate → projection 一致」。
    """
    cursor = raw.get("compact_cursor", 0)
    try:
        cursor_i = max(0, int(cursor))
    except (TypeError, ValueError):
        cursor_i = 0
    try:
        frozen = max(0, int(raw.get("c1_frozen_until") or 0))
    except (TypeError, ValueError):
        frozen = 0
    c2_summary_text = str(raw.get("c2_summary_text") or "")
    cp = _parse_checkpoint(raw.get("compact_checkpoint"))
    if cp is not None:
        cursor_i = max(cursor_i, int(cp.anchor_cursor or 0))
        frozen = max(frozen, int(cp.anchor_frozen_until or 0))
        if not (c2_summary_text or "").strip():
            # resume：摘要文本由锚点回填，保证 KV 前缀字节稳定
            c2_summary_text = str(cp.anchor_summary or "")
    todos = raw.get("todos") if isinstance(raw.get("todos"), list) else []
    tasks = raw.get("tasks") if isinstance(raw.get("tasks"), list) else []
    rfs = raw.get("read_file_state")
    if not isinstance(rfs, dict):
        rfs = {}
    spec = raw.get("speculation") if isinstance(raw.get("speculation"), list) else []
    nested = raw.get("loaded_nested_instruction_paths")
    if not isinstance(nested, list):
        nested = []
    nested_hashes = raw.get("nested_hashes")
    if not isinstance(nested_hashes, dict):
        nested_hashes = {}
    try:
        epoch = int(raw.get("session_md_tool_epoch") or 0)
    except (TypeError, ValueError):
        epoch = 0
    # T31 durable 模式记录 —— 坏值/缺失回退默认（fail-closed，不 crash）。
    agent_mode = str(raw.get("agent_mode") or "agent").strip().lower()
    if agent_mode not in ("agent", "plan", "ask"):
        agent_mode = "agent"
    output_mode = str(raw.get("output_mode") or "").strip().lower()
    if output_mode not in ("lite", "full", "ultra"):
        output_mode = ""
    code_mode = str(raw.get("code_mode") or "").strip().lower()
    if code_mode not in ("lite", "full", "ultra"):
        code_mode = ""
    return WorkingSnapshot(
        session_id=str(raw.get("session_id") or session_id or ""),
        agent_id=str(raw.get("agent_id") or "main"),
        compact_cursor=cursor_i,
        c1_frozen_until=frozen,
        c2_summary_text=c2_summary_text,
        compact_checkpoint=cp,
        turns_since_c2=max(0, int(raw.get("turns_since_c2") or 0)),
        last_model_call_at=_parse_dt(raw.get("last_model_call_at")),
        last_cache_hit_tokens=max(0, int(raw.get("last_cache_hit_tokens") or 0)),
        last_prompt_tokens=max(0, int(raw.get("last_prompt_tokens") or 0)),
        last_x_sim=str(raw.get("last_x_sim") or ""),
        last_action=str(raw.get("last_action") or ""),
        last_x_sent=str(raw.get("last_x_sent") or ""),
        speculation=[str(x) for x in spec],
        loaded_nested_instruction_paths=[str(x) for x in nested],
        nested_hashes={str(k): str(v) for k, v in nested_hashes.items()},
        todos=[x for x in todos if isinstance(x, dict)],
        tasks=[x for x in tasks if isinstance(x, dict)],
        read_file_state={str(k): v for k, v in rfs.items() if isinstance(v, dict)},
        session_md_tool_epoch=max(0, epoch),
        agent_mode=agent_mode,
        output_compact=bool(raw.get("output_compact")),
        output_mode=output_mode,
        code_compact=bool(raw.get("code_compact")),
        code_mode=code_mode,
        reasoning_tail=bool(raw.get("reasoning_tail")),
        current_atoms=[x for x in raw.get("current_atoms") if isinstance(x, dict)]
        if isinstance(raw.get("current_atoms"), list)
        else [],
        last_projection=_parse_projection(raw.get("last_projection")),
    )


def hydrate(session_id: str) -> WorkingSnapshot:
    """从 sidecar 读回 WorkingSnapshot；缺文件或坏 JSON 时返回默认空快照"""
    sid = (session_id or "").strip()
    empty = WorkingSnapshot(session_id=sid)
    if not sid:
        return empty
    path = path_for(sid)
    if not path.is_file():
        return empty
    try:
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    try:
        snap = _from_dict(raw, sid)
    except (TypeError, ValueError):
        return empty
    snap.session_id = sid
    return snap


def flush(session_id: str, snap: WorkingSnapshot) -> None:
    """把 WorkingSnapshot 原子写回 sidecar，供重启后续聊。

    落盘失败只记日志不抛：调用方多在 finally 收尾链上，抛出会吞掉
    后续的 journal 终态 / task_state 复位（曾致重启误报 recovery_required）。
    """
    sid = (session_id or snap.session_id or "").strip()
    if not sid:
        return
    snap.session_id = sid
    path = path_for(sid)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_to_dict(snap), ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logging.getLogger(__name__).warning(
            "working snapshot flush failed session=%s", sid, exc_info=True
        )
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def reset_after_rollback(session_id: str) -> None:
    """Drop compression / projection sidecar state after transcript rewind.

    Chat-only rewinds truncate JSONL but leave ``.working.json`` untouched unless
    we reset it here.  Stale ``c2_summary_text`` would otherwise re-inject
    truncated conversation back into the model via C2 projection.
    """
    sid = (session_id or "").strip()
    if not sid:
        return
    snap = hydrate(sid)
    snap.session_id = sid
    snap.compact_cursor = 0
    snap.c1_frozen_until = 0
    snap.c2_summary_text = ""
    snap.turns_since_c2 = 0
    snap.last_x_sim = ""
    snap.last_x_sent = ""
    snap.last_action = ""
    snap.speculation = []
    snap.todos = []
    snap.tasks = []
    snap.read_file_state = {}
    snap.session_md_tool_epoch = 0
    snap.proj_cache = None
    snap.compact_checkpoint = None
    snap._pending_c2_summary = None
    snap.last_projection = None
    snap.current_atoms = []
    flush(sid, snap)


def note_c2(snap: WorkingSnapshot, new_cursor: int) -> None:
    """记录一次 C2：游标只前进，左段整体冻结，并把 turns_since_c2 清零。

    compact 后清空嵌套指令路径，下一枪按需重新发现（避免挂已滚出窗口的旧规则）。
    """
    assert new_cursor >= snap.compact_cursor
    snap.compact_cursor = new_cursor
    snap.c1_frozen_until = max(snap.c1_frozen_until, new_cursor)
    snap.turns_since_c2 = 0
    snap.proj_cache = None
    # 注意：不在此清 _pending_c2_summary——T8 预取结果需在 note_c2 之后、apply_c2_messages
    # 读取前依然可消费；由 _resolve_c2_summary 消费后置空，或用 reset_after_rollback 兜底。
    snap.loaded_nested_instruction_paths = []


def note_c1(snap: WorkingSnapshot, new_until: int) -> None:
    """记录一次 C1-freeze：冻结边界只前进，并把 turns_since_c2 清零（中间编辑冷却通用）"""
    assert new_until >= snap.c1_frozen_until
    snap.c1_frozen_until = new_until
    snap.turns_since_c2 = 0
    snap.proj_cache = None


def note_shot(snap: WorkingSnapshot, *, hit: int, prompt: int, at: datetime) -> None:
    """记录本轮模型请求的命中/长度/时间，并把 turns_since_c2 加一"""
    snap.last_cache_hit_tokens = hit
    snap.last_prompt_tokens = prompt
    snap.last_model_call_at = at
    snap.turns_since_c2 += 1


def apply_to_tools(snap: WorkingSnapshot, tools: Any) -> None:
    """把 sidecar 里的 todos / read_file_state 灌回工具侧共享 store。"""
    getter = getattr(tools, "get", None)
    todo_tool = getter("TodoWrite") if callable(getter) else None
    store = getattr(todo_tool, "_store", None) if todo_tool is not None else None
    if store is not None and hasattr(store, "set"):
        try:
            from tools.todo_write_tool.types import todo_item_from_raw

            items = [todo_item_from_raw(x) for x in snap.todos]
            store.set([t for t in items if t is not None])
        except Exception:
            _logger.debug("todo hydrate failed", exc_info=True)
    table = getattr(tools, "_tools", None) or {}
    for tool in list(table.values()) if isinstance(table, dict) else []:
        loader = getattr(tool, "_read_state", None)
        if loader is None or not hasattr(loader, "load_meta"):
            continue
        try:
            loader.load_meta(snap.read_file_state)
        except Exception:
            _logger.debug("read_file_state hydrate failed", exc_info=True)
        break


def collect_from_tools(snap: WorkingSnapshot, tools: Any) -> None:
    """从工具侧共享 store 收回 todos / read_file_state，供 flush。"""
    getter = getattr(tools, "get", None)
    todo_tool = getter("TodoWrite") if callable(getter) else None
    store = getattr(todo_tool, "_store", None) if todo_tool is not None else None
    if store is not None and hasattr(store, "get"):
        try:
            snap.todos = [t.to_dict() for t in store.get()]
        except Exception:
            _logger.debug("todo collect failed", exc_info=True)
    table = getattr(tools, "_tools", None) or {}
    for tool in list(table.values()) if isinstance(table, dict) else []:
        state = getattr(tool, "_read_state", None)
        if state is None or not hasattr(state, "snapshot_meta"):
            continue
        try:
            snap.read_file_state = state.snapshot_meta()
        except Exception:
            _logger.debug("read_file_state collect failed", exc_info=True)
        break


# --------------------------------------------------------------------------- #
# T31 跨入口模式 SSOT —— durable 模式记录解析 / 投影。
# --------------------------------------------------------------------------- #
# 请求体里「未提供」的字段用 None 表达（bool=False / str="" 视为显式值）。
# 这样客户端只在用户真的改过模式时才发值：恢复会话时 durable 记录自动胜出。

def _norm_agent(value: object) -> str:
    mode = str(value or "agent").strip().lower()
    return mode if mode in ("agent", "plan", "ask") else "agent"


def _norm_quad(value: object, *, default: str) -> str:
    mode = str(value or default).strip().lower()
    return mode if mode in ("lite", "full", "ultra") else default


def resolve_modes(
    snap: WorkingSnapshot,
    *,
    agent_mode: object | None = None,
    output_compact: object | None = None,
    output_mode: object | None = None,
    code_compact: object | None = None,
    code_mode: object | None = None,
    reasoning_tail: object | None = None,
) -> dict[str, Any]:
    """求本回合生效模式：durable 记录为权威源，请求体作投影覆盖。

    语义（T31）：
    - 字段在请求体里**显式提供**（agent_mode/output_compact 等非 None）而非
      None → 该字段以请求体为准（投影覆盖）。
    - 字段为 None（客户端没有设置意图，如 cli-ts 恢复会话）→ 以 durable 记录
      为准；durable 从未设置时回退默认（agent / off）。
    """
    eff_agent = _norm_agent(agent_mode) if agent_mode is not None else _norm_agent(
        getattr(snap, "agent_mode", "agent")
    )
    eff_out_compact = (
        bool(output_compact)
        if output_compact is not None
        else bool(getattr(snap, "output_compact", False))
    )
    eff_out_mode = (
        _norm_quad(output_mode, default="") if output_mode is not None else _norm_quad(
            getattr(snap, "output_mode", ""), default=""
        )
    )
    eff_code_compact = (
        bool(code_compact)
        if code_compact is not None
        else bool(getattr(snap, "code_compact", False))
    )
    eff_code_mode = (
        _norm_quad(code_mode, default="") if code_mode is not None else _norm_quad(
            getattr(snap, "code_mode", ""), default=""
        )
    )
    eff_reasoning_tail = (
        bool(reasoning_tail)
        if reasoning_tail is not None
        else bool(getattr(snap, "reasoning_tail", False))
    )
    return {
        "agent_mode": eff_agent,
        "output_compact": eff_out_compact,
        "output_mode": eff_out_mode,
        "code_compact": eff_code_compact,
        "code_mode": eff_code_mode,
        "reasoning_tail": eff_reasoning_tail,
    }


def apply_modes(snap: WorkingSnapshot, modes: dict[str, Any]) -> None:
    """把生效模式写回 durable 记录（供 flush 持久化 + 后续 resume 重放）。"""
    snap.agent_mode = _norm_agent(modes.get("agent_mode"))
    snap.output_compact = bool(modes.get("output_compact"))
    snap.output_mode = _norm_quad(modes.get("output_mode"), default="")
    snap.code_compact = bool(modes.get("code_compact"))
    snap.code_mode = _norm_quad(modes.get("code_mode"), default="")
    snap.reasoning_tail = bool(modes.get("reasoning_tail"))

