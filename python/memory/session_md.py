"""L5b 会话任务语义笔记（给模型看，不是机器状态）。

磁盘：~/.xeyo/sessions/{id}/session.md
权威边界：只写 Goal / Current / Completed / discoveries / Open / Next + Facts。
禁止写入 todos、cwd、cursor、hit_tokens。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from memory.working import WorkingSnapshot, _safe_name, _sessions_dir

TEMPLATE = """# Session
## Goal
{goal}
## Current state
{current}
## Completed
{completed}
## Important discoveries
{discoveries}
## Key facts
{facts}
## Open questions
{open_questions}
## Next action
{next_action}
"""

_FORBIDDEN = (
    "compact_cursor",
    "prompt_cache",
    "hit_tokens",
    "- [ ]",
    "- [x]",
)

MIN_TOOL_CALLS = 8
REWRITE_GAP = 8


# P2-2 任务级 rollout 归档（对齐 Codex rollout_summaries/<slug>.md）：
# 会话/任务结束时把 session.md 归档一份到 memdir/rollout_summaries/，喂 L4 检索；
# 只保留最新 N 份（按归档时间），绝不做每轮全量重建（红线②）。
ENV_ROLLOUT_MAX = "XEYO_MEMORY_ROLLOUT_MAX"
DEFAULT_ROLLOUT_MAX = 20


def rollout_dir(wsid: str) -> Path:
	"""任务级 rollout 归档目录（~/.xeyo/memory/{wsid}/rollout_summaries/）。"""
	from memory.memdir import memdir_root

	return memdir_root(wsid) / "rollout_summaries"


def _rollout_stem(session_id: str) -> str:
	"""归档文件名 stem：会话 id 的安全化形式（对齐 _safe_name 语义）。"""
	return _safe_name(session_id) or "session"


def _rollout_max_keep() -> int:
	import os as _os

	try:
		return max(1, int(_os.environ.get(ENV_ROLLOUT_MAX, "").strip() or DEFAULT_ROLLOUT_MAX))
	except (TypeError, ValueError):
		return DEFAULT_ROLLOUT_MAX


def _prune_rollouts(directory: Path, *, max_keep: int) -> int:
	"""按文件 mtime 保留最新 max_keep 份；返回删除数。尽力而为，不抛。"""
	removed = 0
	try:
		files = sorted(
			(p for p in directory.glob("*.md") if p.is_file()),
			key=lambda p: p.stat().st_mtime,
			reverse=True,
		)
		for p in files[max_keep:]:
			try:
				p.unlink()
				removed += 1
			except OSError:
				continue
	except OSError:
		return removed
	return removed


def archive_session_rollout(
	session_id: str, *, wsid: str, max_keep: int | None = None
) -> Path | None:
	"""会话/任务结束后归档任务级 rollout 摘要；返回归档路径，无正文返回 None。

	- 只读 session.md（不读 JSONL、不动历史），按需重写一次归档文件（原子替换）；
	- 头部含 session_id / archived_at（供检索与引用），正文 = session.md 七段；
	- 顺带裁剪到最新 ``XEYO_MEMORY_ROLLOUT_MAX``（默认 20）份；
	- 任何失败返回 None（归档是增强项，绝不阻塞会话收尾）。
	"""
	sid = (session_id or "").strip()
	if not sid or not wsid:
		return None
	try:
		text = load(sid)
		if not text:
			return None
		d = rollout_dir(wsid)
		d.mkdir(parents=True, exist_ok=True)
		path = d / f"{_rollout_stem(sid)}.md"
		header = (
			"---\n"
			f"session_id: {sid}\n"
			f"archived_at: {datetime.now().astimezone().isoformat()}\n"
			"---\n"
		)
		tmp = path.with_suffix(".md.tmp")
		tmp.write_text(header + text.rstrip() + "\n", encoding="utf-8")
		os.replace(tmp, path)
		# A4 write-through：归档落盘即同步进 sqlite 派生索引（尽力而为）
		try:
			from memory import memindex

			memindex.upsert_rollout_file(wsid, path)
		except Exception:  # noqa: BLE001
			pass
		_prune_rollouts(
			d, max_keep=max_keep if max_keep is not None else _rollout_max_keep()
		)
		return path
	except (OSError, ValueError):
		return None


def path_for(session_id: str) -> Path:
    """返回本会话任务语义笔记路径（~/.xeyo/sessions/{id}/session.md）"""
    return _sessions_dir() / _safe_name(session_id) / "session.md"


def load(session_id: str) -> str | None:
    """读取 session.md 正文；不存在则返回 None，供 C2 左段使用"""
    sid = (session_id or "").strip()
    if not sid:
        return None
    path = path_for(sid)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def clear_after_rollback(session_id: str, *, keep_tool_calls: int | None = None) -> None:
    """回滚后的 session.md 处理（A5 差分重写）。

    - ``keep_tool_calls=None``（缺省/无法计量）：旧行为——整文件删除（fail-closed）；
    - ``keep_tool_calls=N``：**精确截断**——只保留 turn ≤ N 的 delta 并重放重建
      物化文件（回滚不再失忆）；无 delta 可存（或从未 delta 化）→ 退回整删。
    """
    sid = (session_id or "").strip()
    if not sid:
        return
    path = path_for(sid)
    if keep_tool_calls is None:
        _unlink_quiet(path)
        _unlink_quiet(path_deltas(sid))
        return
    try:
        text = rebuild_from_deltas(sid, upto_turn=int(keep_tool_calls))
    except Exception:  # noqa: BLE001 — 回滚路径绝不因增强项失败
        text = None
    if not text or not text.strip():
        # 无可存叙事（delta 全在截断点之后 / 从未 delta 化）→ 旧行为整删
        _unlink_quiet(path)
        _unlink_quiet(path_deltas(sid))
        return
    try:
        _atomic_write_text(path, text)
    except OSError:
        pass


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# A5 差分重写（Stage 1 确定性）：全量重写 → 「diff → 追加 delta → 工程侧合并」。
#
# - ``session_deltas.jsonl`` 每行 = {ts, turn, author, sections:{节头: 新节全文}}，
#   只记 **Changed 节**；物化 session.md = fold(deltas)（读者继续读物化文件，零改动）。
# - 单条 delta 有误只废一条：日志可回放/可截断（rewind 精确到 turn），不会一错到底。
# - Stage 2（模型 delta）预留：author 字段区分 det/model；本阶段只有 det。
# --------------------------------------------------------------------------- #

_SECTION_ORDER = (
    "## Goal",
    "## Current state",
    "## Completed",
    "## Important discoveries",
    "## Key facts",
    "## Open questions",
    "## Next action",
)
_SESSION_TITLE = "# Session"


def deltas_enabled() -> bool:
    """A5 差分重写：**已固化开启**（原 XEYO_SESSION_MD_DELTA 键已删，回退只能改源码）。"""
    return True


def path_deltas(session_id: str) -> Path:
    """本会话 delta 日志路径（~/.xeyo/sessions/{id}/session_deltas.jsonl）。"""
    return _sessions_dir() / _safe_name(session_id) / "session_deltas.jsonl"


def _strip_forbidden(text: str) -> str:
    for token in _FORBIDDEN:
        text = text.replace(token, "")
    return re.sub(r"- \[[ xX]\]", "", text)


def _split_sections(text: str) -> dict[str, str]:
    """把 session.md 正文切成 {节头: 该节全文（含节头行）}；顺序无关。"""
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf).strip("\n")
            cur = stripped
            buf = [line]
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip("\n")
    return out


def _fold_sections(state: dict[str, str]) -> str:
    """按模板节序把节状态折回完整 session.md 文本（与 render 同构）。"""
    parts = [_SESSION_TITLE]
    for header in _SECTION_ORDER:
        body = state.get(header)
        if body:
            parts.append(body)
    return "\n".join(parts).strip() + "\n"


def append_delta(session_id: str, row: dict[str, Any]) -> bool:
    """追加一条 delta（JSONL 单行）；尽力而为，失败返回 False。"""
    path = path_deltas(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except OSError:
        return False


def read_deltas(session_id: str) -> list[dict[str, Any]]:
    """读全部 delta（坏行跳过——单条损坏不影响历史）。"""
    path = path_deltas(session_id)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and isinstance(row.get("sections"), dict):
                rows.append(row)
    except OSError:
        return []
    return rows


def fold_deltas(rows: list[dict[str, Any]], *, upto_turn: int | None = None) -> dict[str, str]:
    """按序合并 delta → 节状态（工程侧合并点；Stage2 模型 delta 也走这里）。"""
    state: dict[str, str] = {}
    for row in rows:
        try:
            turn = int(row.get("turn") or 0)
        except (TypeError, ValueError):
            turn = 0
        if upto_turn is not None and turn > upto_turn:
            continue
        sections = row.get("sections")
        if isinstance(sections, dict):
            for header, body in sections.items():
                if isinstance(body, str) and body.strip():
                    state[str(header)] = body
    return state


def rebuild_from_deltas(session_id: str, *, upto_turn: int | None = None) -> str | None:
    """重放 delta 重建物化 session.md（可截断到 turn ≤ upto_turn）；无可存返回 None。"""
    state = fold_deltas(read_deltas(session_id), upto_turn=upto_turn)
    if not state:
        return None
    return _fold_sections(state)


def _text_of(msg: dict[str, Any]) -> str:
    """取出消息里给人看的纯文本。"""
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
            elif isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(p for p in parts if p).strip()
    return ""


def _is_tool_msg(msg: dict[str, Any]) -> bool:
    """是否为 tool_result / role=tool。"""
    if msg.get("role") == "tool":
        return True
    content = msg.get("content")
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def count_tool_calls(messages: list[dict[str, Any]]) -> int:
    """统计历史里的工具结果条数，用作 session.md 重写节流。"""
    return sum(1 for m in messages if _is_tool_msg(m))


def count_tool_results_rows(rows: list[Any]) -> int | None:
    """对转录行（形状不保证）尽力统计工具结果条数；无法判定返回 None。

    供回滚路径把「delta 截断点」对齐到保留转录：形如 role=tool / content 含
    tool_result / type==tool_result 的行都计一次；解析失败整体返回 None
    （调用方退回旧行为整删）。
    """
    if not isinstance(rows, list):
        return None
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            return None
        if row.get("role") == "tool" or row.get("type") == "tool_result":
            n += 1
            continue
        content = row.get("content") or row.get("message")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            n += 1
            continue
        if isinstance(content, dict) and content.get("type") == "tool_result":
            n += 1
    return n


def _clip(text: str, n: int = 400) -> str:
    """截断并去掉会污染 session.md 的机器字段。"""
    cleaned = " ".join((text or "").split())
    for token in _FORBIDDEN:
        cleaned = cleaned.replace(token, "")
    cleaned = re.sub(r"- \[[ xX]\]", "", cleaned)
    if len(cleaned) > n:
        return cleaned[: n - 1] + "…"
    return cleaned


def _tool_paths_and_facts(messages: list[dict[str, Any]]) -> list[str]:
    """从工具结果确定性抽取路径 / 取值事实（供 Key facts）。"""
    from memory.summarize import extract_tool_summary, extract_value_facts

    facts: list[str] = []
    seen: set[str] = set()
    path_re = re.compile(r"[\\/][\w.\-\\/]+?\.\w{1,8}")
    for msg in messages:
        if not _is_tool_msg(msg):
            continue
        content = msg.get("content")
        chunks: list[str] = []
        name = str(msg.get("name") or "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    chunks.append(str(block.get("content") or ""))
        for raw in chunks:
            for path in path_re.findall(raw)[:4]:
                key = path.strip()
                if key and key not in seen:
                    seen.add(key)
                    facts.append(f"path {key}")
            for k, v in extract_value_facts(raw, limit=4):
                line = f"{k}={v}"
                if line not in seen:
                    seen.add(line)
                    facts.append(line)
            if len(facts) >= 12:
                return facts
            # 短摘要一行（错误优先）
            brief = extract_tool_summary(raw, name, max_text=120)
            if brief and brief not in seen and len(brief) > 16:
                seen.add(brief)
                facts.append(brief)
                if len(facts) >= 12:
                    return facts
    return facts[:12]


def _extract(messages: list[dict[str, Any]]) -> dict[str, str]:
    """从消息确定性抽取七段；不 fork 摘要模型。"""
    users = [
        _text_of(m)
        for m in messages
        if m.get("role") == "user" and _text_of(m) and not _is_tool_msg(m)
    ]
    asst = [
        _text_of(m)
        for m in messages
        if m.get("role") == "assistant" and _text_of(m)
    ]
    tools = count_tool_calls(messages)
    goal = _clip(users[0], 300) if users else "(unspecified)"
    current = _clip(users[-1], 400) if users else "(none)"
    completed = f"{tools} tool results in this session"
    discoveries = _clip(asst[-1], 400) if asst else "(none yet)"
    fact_lines = _tool_paths_and_facts(messages)
    facts = "\n".join(f"- {f}" for f in fact_lines) if fact_lines else "(none yet)"
    questions = [a for a in asst if "?" in a or "？" in a]
    open_q = _clip(questions[-1], 300) if questions else "(none)"
    next_action = _clip(users[-1], 300) if users else "(continue)"
    return {
        "goal": goal or "(unspecified)",
        "current": current or "(none)",
        "completed": completed,
        "discoveries": discoveries or "(none yet)",
        "facts": facts,
        "open_questions": open_q,
        "next_action": next_action,
    }


def render(messages: list[dict[str, Any]]) -> str:
    """把抽取结果填进模板。"""
    return TEMPLATE.format(**_extract(messages)).strip() + "\n"


def maybe_update(
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    min_tool_calls: int = MIN_TOOL_CALLS,
    working: WorkingSnapshot | None = None,
) -> None:
    """超阈值且距上次写 ≥ K 次工具调用才更新；确定性抽取（P0 不 fork 摘要模型）。

    A5 差分重写（默认开）：全量 render 只作 diff 源——与物化现状逐节比较，**只把
    Changed 节追加进 delta 日志**，再由工程侧合并出物化文件（读者零改动）。
    差分重写已固化开启（原 XEYO_SESSION_MD_DELTA 键已删）。
    """
    sid = (session_id or "").strip()
    if not sid:
        return
    n_tools = count_tool_calls(messages)
    if n_tools < min_tool_calls:
        return
    epoch = working.session_md_tool_epoch if working is not None else 0
    path = path_for(sid)
    if path.is_file() and n_tools - epoch < REWRITE_GAP:
        return
    text = _strip_forbidden(render(messages))
    old = load(sid) or ""
    if old.strip() == text.strip():
        # 内容无变化：只推进节流纪元，不写盘（写放大为零）
        if working is not None:
            working.session_md_tool_epoch = n_tools
        return
    if deltas_enabled():
        # ① diff：只记 Changed 节
        new_sections = _split_sections(text)
        old_sections = _split_sections(old)
        changed = {
            h: body
            for h, body in new_sections.items()
            if old_sections.get(h) != body
        }
        # ② 追加 delta（可追溯/可截断/单条可废）
        append_delta(
            sid,
            {
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "turn": int(n_tools),
                "author": "det",
                "sections": changed,
            },
        )
    # ③ 工程侧合并：物化文件照常原子写（读者/C2 左段/peer 检索继续读它）
    _atomic_write_text(path, text)
    if working is not None:
        working.session_md_tool_epoch = n_tools
