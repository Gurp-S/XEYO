"""L6 休眠重塑：NightShift 门闩与投递。

正确性在 governance，本文件不发明晋升规则。
禁止在 query_loop 的 while 里 await。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from memory.governance import (
    MemoryCandidate,
    MemorySchemaError,
    can_promote,
    parse_and_validate,
    promotion_confidence,
    resolve_conflict,
    today_iso,
)
from memory.memdir import (
    candidates_path,
    ensure_layout,
    load_notes,
    load_tombstones,
    memdir_root,
    prune_dead_notes,
    rewrite_index,
    workspace_path,
    write_note,
    USER_MEMDIR_ID,
)

CANDIDATE_THRESHOLD = 20
MEMDIR_BYTES_THRESHOLD = 2_000_000
HOURS_INTERVAL = 24.0

# P1-2 晋升限频（对齐 Codex phase2 成功 cooldown / 阈值跳过）：单轮最多晋升的
# Candidate 条数，超出部分留到下轮 —— 避免晋升风暴。
ENV_PROMOTE_MAX_PER_RUN = "XEYO_MEMORY_PROMOTE_MAX_PER_RUN"
DEFAULT_PROMOTE_MAX_PER_RUN = 8

# P2-1 常驻收敛：成功冷却（对齐 Codex PHASE2_SUCCESS_COOLDOWN_SECONDS=6h）只压制
# 例行触发（候选阈值/体积阈值），绝不压制急件（Forget/冲突 / 有可晋升候选 —— 红线①）。
ENV_COOLDOWN_HOURS = "XEYO_MEMORY_COOLDOWN_HOURS"
DEFAULT_COOLDOWN_HOURS = 6.0
# 常驻收敛链：上次 run 后若仍有活（如被限频截留的可晋升候选），隔 FOLLOWUP_DELAY
# 秒自动再整理一轮，最多链 FOLLOWUP_MAX_CHAIN 次（防无限循环）。
ENV_FOLLOWUP_DELAY = "XEYO_MEMORY_FOLLOWUP_DELAY"
DEFAULT_FOLLOWUP_DELAY = 30.0
ENV_FOLLOWUP_MAX_CHAIN = "XEYO_MEMORY_FOLLOWUP_MAX_CHAIN"
DEFAULT_FOLLOWUP_MAX_CHAIN = 2


def _promote_max_per_run() -> int:
    try:
        return max(1, int(os.environ.get(ENV_PROMOTE_MAX_PER_RUN, "").strip() or DEFAULT_PROMOTE_MAX_PER_RUN))
    except (TypeError, ValueError):
        return DEFAULT_PROMOTE_MAX_PER_RUN


def _cooldown_hours() -> float:
    try:
        return max(0.0, float(os.environ.get(ENV_COOLDOWN_HOURS, "").strip() or DEFAULT_COOLDOWN_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN_HOURS


def _followup_delay() -> float:
    try:
        return max(0.0, float(os.environ.get(ENV_FOLLOWUP_DELAY, "").strip() or DEFAULT_FOLLOWUP_DELAY))
    except (TypeError, ValueError):
        return DEFAULT_FOLLOWUP_DELAY


def _followup_max_chain() -> int:
    try:
        return max(0, int(os.environ.get(ENV_FOLLOWUP_MAX_CHAIN, "").strip() or DEFAULT_FOLLOWUP_MAX_CHAIN))
    except (TypeError, ValueError):
        return DEFAULT_FOLLOWUP_MAX_CHAIN


@dataclass
class NightShiftState:
    """空闲整理的调度状态（不是记忆正确性规则）"""

    last_consolidated_at: datetime | None = None  # 上次成功整理时间
    candidate_count: int = 0  # 待过闸 Candidate 条数
    memdir_bytes: int = 0  # memdir 体积
    pending_forget_or_conflict: bool = False  # 有 Forget 或未消解冲突时必须跑
    baseline_sha: str = ""  # P3：上次成功晋升时的 git HEAD（diff 佐证基线）


def _state_path(wsid: str) -> Path:
    return memdir_root(wsid) / "nightshift.json"


def _lock_path(wsid: str) -> Path:
    return memdir_root(wsid) / ".nightshift.lock"


def load_state(wsid: str) -> NightShiftState:
    """读取调度状态；缺文件当从未整理。"""
    path = _state_path(wsid)
    if not path.is_file():
        return NightShiftState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return NightShiftState()
    at = None
    if raw.get("last_consolidated_at"):
        try:
            at = datetime.fromisoformat(str(raw["last_consolidated_at"]))
        except ValueError:
            at = None
    return NightShiftState(
        last_consolidated_at=at,
        candidate_count=int(raw.get("candidate_count") or 0),
        memdir_bytes=int(raw.get("memdir_bytes") or 0),
        pending_forget_or_conflict=bool(raw.get("pending_forget_or_conflict")),
        baseline_sha=str(raw.get("baseline_sha") or ""),
    )


def save_state(wsid: str, state: NightShiftState) -> None:
    """写回调度状态。"""
    ensure_layout(wsid)
    payload = {
        "last_consolidated_at": (
            state.last_consolidated_at.isoformat() if state.last_consolidated_at else None
        ),
        "candidate_count": state.candidate_count,
        "memdir_bytes": state.memdir_bytes,
        "pending_forget_or_conflict": state.pending_forget_or_conflict,
        "baseline_sha": state.baseline_sha,
    }
    _state_path(wsid).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def memdir_size(wsid: str) -> int:
    """统计 memdir 字节数。"""
    root = memdir_root(wsid)
    if not root.is_dir():
        return 0
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def _load_candidate_rows(wsid: str) -> list[dict]:
    """读取 Candidate JSONL 原始行（含 first_seen/last_seen/hit_count 时间戳）。"""
    path = candidates_path(wsid)
    if not path.is_file():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return rows
    return rows


def _cand_from_row(row: dict) -> MemoryCandidate:
    src = dict(row.get("source") or {}) if isinstance(row.get("source"), dict) else {}
    if row.get("hit_count") is not None and "hit_count" not in src:
        try:
            src["hit_count"] = int(row["hit_count"])
        except (TypeError, ValueError):
            pass
    return MemoryCandidate(
        content=str(row.get("content") or ""),
        source=src,
        evidence=list(row.get("evidence") or []),
    )


def load_candidates(wsid: str) -> list[MemoryCandidate]:
    """读取 Candidate JSONL。"""
    return [_cand_from_row(r) for r in _load_candidate_rows(wsid)]


def save_candidates(wsid: str, cands: list[MemoryCandidate]) -> None:
    """写回未过闸 Candidate。"""
    ensure_layout(wsid)
    path = candidates_path(wsid)
    lines = [
        json.dumps(
            {"content": c.content, "source": c.source, "evidence": c.evidence},
            ensure_ascii=False,
        )
        for c in cands
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def append_candidates(wsid: str, new: list[MemoryCandidate]) -> int:
    """追加 Candidate 到 JSONL；同 content 去重。

    去重命中时刷新该行的 ``source``（及可选 ``last_seen``），避免重复 live 跑
    后 ``session_id`` 仍指向旧批次。返回**新追加**条数（刷新不算追加）。
    """
    if not new:
        return 0
    ensure_layout(wsid)
    path = candidates_path(wsid)

    rows: list[dict] = []
    index: dict[str, int] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            key = str(row.get("content") or "").strip().casefold()
            if not key:
                continue
            index[key] = len(rows)
            rows.append(row)

    added = 0
    touched = False
    now = datetime.now(timezone.utc).isoformat()
    for c in new:
        content = (c.content or "").strip()
        if not content:
            continue
        key = content.casefold()
        if key in index:
            i = index[key]
            old = rows[i]
            src = dict(c.source or {}) if isinstance(c.source, dict) else {}
            merged = (
                dict(old.get("source") or {})
                if isinstance(old.get("source"), dict)
                else {}
            )
            if src:
                merged.update(src)
            prev_hit = int(merged.get("hit_count") or old.get("hit_count") or 1)
            merged["hit_count"] = prev_hit + 1
            old["source"] = merged
            old["hit_count"] = merged["hit_count"]
            old["last_seen"] = now
            if c.evidence:
                ev = list(old.get("evidence") or [])
                for e in c.evidence:
                    if e not in ev:
                        ev.append(e)
                old["evidence"] = ev
            rows[i] = old
            touched = True
            continue
        index[key] = len(rows)
        src0 = dict(c.source or {}) if isinstance(c.source, dict) else {}
        src0.setdefault("hit_count", 1)
        rows.append(
            {
                "content": c.content,
                "source": src0,
                "evidence": c.evidence,
                "hit_count": 1,
                "first_seen": now,
                "last_seen": now,
            }
        )
        added += 1
        touched = True

    if not touched:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(r, ensure_ascii=False) + "\n"
            for r in rows
        ),
        encoding="utf-8",
    )
    return added


LOCK_STALE_SECONDS = 3600.0  # 锁文件超过此时长且 PID 不可达 → 回收


def _pid_alive(pid: int) -> bool:
	"""尽力判断 PID 是否仍存活（跨平台）。"""
	if pid <= 0:
		return False
	try:
		os.kill(pid, 0)
		return True
	except ProcessLookupError:
		return False
	except PermissionError:
		# 无权限发信号，但进程可能仍在 → 视为存活
		return True
	except OSError:
		return False


def _try_reclaim_stale_lock(path: Path) -> bool:
	"""若锁过期且持有者已死，删除锁并返回 True。"""
	try:
		age = max(0.0, time.time() - path.stat().st_mtime)
	except OSError:
		return False
	pid = 0
	try:
		raw = path.read_text(encoding="utf-8").strip()
		pid = int(raw.split()[0]) if raw else 0
	except (OSError, ValueError, IndexError):
		pid = 0
	if pid and _pid_alive(pid) and age < LOCK_STALE_SECONDS:
		return False
	if pid and _pid_alive(pid):
		# 活着但过期很久：仍不抢（可能是长跑整理）
		if age < LOCK_STALE_SECONDS * 6:
			return False
	try:
		path.unlink()
		return True
	except OSError:
		return False


def has_lock(workspace_id: str) -> bool:
	"""尝试取得该工作区 NightShift 文件锁；未拿到则本轮跳过。

	崩溃残留：锁内写 PID；持有者已死或锁过期时可回收后重试一次。
	"""
	ensure_layout(workspace_id)
	path = _lock_path(workspace_id)
	for _attempt in range(2):
		try:
			fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
			try:
				os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
			finally:
				os.close(fd)
			return True
		except FileExistsError:
			if _attempt == 0 and _try_reclaim_stale_lock(path):
				continue
			return False
		except OSError:
			return False
	return False


def release_lock(workspace_id: str) -> None:
    """释放 NightShift 文件锁。"""
    path = _lock_path(workspace_id)
    try:
        path.unlink()
    except OSError:
        pass


def should_run(state: NightShiftState, workspace_id: str) -> bool:
	"""是否该整理：24h / Candidate 超阈 / 体积超阈 / 有 Forget 或冲突 / 有可晋升候选。

	禁止写成「少于 5 session 就永不跑」。有 ``can_promote`` 的候选时不应被 24h
	门闩卡死在 candidates（否则跨会话 search 永远搜不到收割事实）。

	P2-1 成功冷却：上次成功整理后 ``XEYO_MEMORY_COOLDOWN_HOURS``（默认 6h，对齐
	Codex PHASE2_SUCCESS_COOLDOWN_SECONDS）内，**例行**触发（阈值/体积）跳过；
	急件（Forget/冲突、或存在可晋升候选）永远不被冷却压制 —— 冷却只挡例行风暴。
	"""
	hours = 10_000.0
	if state.last_consolidated_at is not None:
		now = datetime.now(tz=state.last_consolidated_at.tzinfo)
		hours = max(0.0, (now - state.last_consolidated_at).total_seconds() / 3600.0)
	# 急件优先：Forget/未消解冲突必须跑；可晋升候选不被冷却/24h 卡住（红线①）
	if state.pending_forget_or_conflict:
		return True
	try:
		if any(can_promote(c) for c in load_candidates(workspace_id)):
			return True
	except OSError:
		pass
	# P2-1 成功冷却：冷却窗口内例行触发跳过（阈值/体积不构成急件）
	if hours < _cooldown_hours():
		return False
	return (
		hours >= HOURS_INTERVAL
		or state.candidate_count > CANDIDATE_THRESHOLD
		or state.memdir_bytes > MEMDIR_BYTES_THRESHOLD
	)



def _expired(note) -> bool:
    if not note.expires_at:
        return False
    return str(note.expires_at) < today_iso()


def run(workspace_id: str) -> None:
    """在 memdir 内蒸馏 Candidate、消解冲突、丢掉过期、遵守 tombstone，最后只 rewrite_index 一次"""
    # P1-2 保留期剪枝：先剪超期非 active note 文件，再读集合
    # （active 事实与可能晋升的候选绝不剪——红线①）。剪掉也算变更（索引须重写）。
    try:
        pruned = prune_dead_notes(workspace_id)
    except OSError:
        pruned = 0
    changed = pruned > 0
    # P3 改动 diff 佐证：相对上次成功晋升基线的 git 改动，只在本轮（晋升前）收集一次；
    # 非 git / 无改动 → 无证据、不降权（红线②：绝不做每轮重比对）。
    prev_state = load_state(workspace_id)
    diff = None
    diff_paths: set[str] = set()
    try:
        from memory.workspace_diff import collect as _collect_diff

        cwd = workspace_path(workspace_id)
        if cwd:
            diff = _collect_diff(cwd, baseline_sha=prev_state.baseline_sha)
        if diff is not None:
            from memory.workspace_diff import write_artifact as _write_artifact

            _write_artifact(workspace_id, diff)
            diff_paths = set(diff.paths)
    except Exception:  # noqa: BLE001 — 佐证失败不阻塞整理
        diff = None
        diff_paths = set()
    stones = load_tombstones(workspace_id)
    tomb_ids = {s.id for s in stones}
    notes = load_notes(workspace_id)
    kept = []
    for note in notes:
        if note.id in tomb_ids:
            if note.status != "deleted":
                write_note(replace(note, status="deleted"), wsid=workspace_id)
                changed = True
            continue
        if _expired(note) and note.status == "active":
            write_note(replace(note, status="deleted"), wsid=workspace_id)
            changed = True
            continue
        kept.append(note)
    # 冲突：同 scope 互斥则 supersede
    survivors = list(kept)
    i = 0
    while i < len(survivors):
        j = i + 1
        while j < len(survivors):
            a, b = survivors[i], survivors[j]
            verdict = resolve_conflict(a, b)
            if verdict == "supersede" and a.status == "active" and b.status == "active":
                write_note(replace(a, status="superseded"), wsid=workspace_id)
                survivors[i] = replace(a, status="superseded")
                changed = True
            elif verdict == "keep_old" and b.status == "active":
                write_note(replace(b, status="superseded"), wsid=workspace_id)
                survivors[j] = replace(b, status="superseded")
                changed = True
            j += 1
        i += 1
    leftover: list[MemoryCandidate] = []
    promoted = 0
    forgotten_text = {
        n.content.strip()
        for n in notes
        if n.id in tomb_ids or n.status == "deleted"
    }
    for cand in load_candidates(workspace_id):
        cand_id = str((cand.source or {}).get("id") or "")
        if cand_id in tomb_ids or cand.content.strip() in forgotten_text:
            continue
        # P3：候选提及的路径命中本轮工作区改动 → 注入 verified_by_diff 佐证
        # （先打标 can_promote 才放行；绝不把「没改过」当证据）。
        if diff_paths:
            try:
                from memory.workspace_diff import candidate_path_tokens, matches

                if matches(candidate_path_tokens(cand.content, cand.evidence), diff_paths):
                    ev = list(cand.evidence)
                    if "verified_by_diff" not in ev:
                        ev.append("verified_by_diff")
                        cand.evidence = ev
            except Exception:  # noqa: BLE001
                pass
        if not can_promote(cand):
            leftover.append(cand)
            continue
        # P1-2 晋升限频：本轮已达上限则留到下轮（低于阈值跳过，防晋升风暴）。
        if promoted >= _promote_max_per_run():
            leftover.append(cand)
            continue
        promoted += 1
        conf = promotion_confidence(cand)
        src = dict(cand.source or {})
        if not src.get("kind"):
            src["kind"] = "nightshift"
        # scope=user 候选写到用户级 memdir（由 write_note 按 scope 路由）
        scope = str(src.get("scope") or "workspace")
        if scope not in {"user", "workspace", "project", "task"}:
            scope = "workspace"
        try:
            note = parse_and_validate(
                {
                    "type": "feedback",
                    "source": src,
                    "confidence": conf,
                    "status": "active",
                    "scope": scope,
                },
                cand.content,
            )
        except MemorySchemaError:
            leftover.append(cand)
            continue
        if note.id in tomb_ids:
            continue
        write_note(note, wsid=workspace_id)
        changed = True
    save_candidates(workspace_id, leftover)
    # 索引只在发生变更时重写（changed 标志原被 `_ = changed` 弃用）。run() 内全部
    # note 集变更路径（剪枝/tombstone/过期/冲突/晋升）都会置 changed；外部手改
    # topics/*.md 不在契约内，下次任一变更发生时索引会自愈。
    if changed:
        fresh = load_notes(workspace_id)
        rewrite_index(fresh, wsid=workspace_id)
        # user 域索引单独重写（晋升可能写到 ~/.xeyo/memory/user/）
        try:
            ensure_layout(USER_MEMDIR_ID)
            rewrite_index(load_notes(USER_MEMDIR_ID), wsid=USER_MEMDIR_ID)
        except OSError:
            pass
    state = NightShiftState(
        last_consolidated_at=datetime.now(timezone.utc),
        candidate_count=len(leftover),
        memdir_bytes=memdir_size(workspace_id),
        pending_forget_or_conflict=False,
        # P3：推进 diff 基线到本轮 HEAD（无 diff/非 git 则保持原基线）
        baseline_sha=(diff.head_sha if diff is not None else prev_state.baseline_sha),
    )
    save_state(workspace_id, state)
    # P3：基线与磁盘状态一致后清除工件（防止 4MB 级工件污染 memdir 体积与下一次证据）
    if diff is not None:
        try:
            from memory.workspace_diff import remove_artifact

            remove_artifact(workspace_id)
        except Exception:  # noqa: BLE001
            pass
    try:
        from memory.instruction_maintain import refresh_instruction_proposals

        refresh_instruction_proposals(workspace_id)
    except Exception:
        pass


def _run_safe(workspace_id: str, *, chain_budget: int = 0) -> bool:
    """带锁跑整理；拿不到锁则跳过。返回是否仍建议后续收敛（常驻链用）。

    chain_budget>0 且本次 run 后仍有活（如被限频截留的可晋升候选）→ True，
    调用方据此再排一轮；为 False 则收敛链结束。
    """
    if not has_lock(workspace_id):
        return False
    try:
        state = load_state(workspace_id)
        state.candidate_count = len(load_candidates(workspace_id))
        state.memdir_bytes = memdir_size(workspace_id)
        if not should_run(state, workspace_id):
            return False
        run(workspace_id)
        if chain_budget <= 0:
            return False
        return should_run(load_state(workspace_id), workspace_id)
    finally:
        release_lock(workspace_id)


async def _run_async(workspace_id: str, *, remaining: int | None = None) -> None:
    """线程外也不阻塞事件循环太久：同步 run 包一层。

    P2-1 常驻收敛：跑完若有活（急件仍存在，例如被晋升限频截留的候选），
    隔 ``FOLLOWUP_DELAY`` 秒自动续一轮，直到收敛或链预算耗尽（防无限循环）。
    """
    chain = _followup_max_chain() if remaining is None else remaining
    more = await asyncio.to_thread(_run_safe, workspace_id, chain_budget=chain)
    if not more or chain <= 0:
        return
    delay = _followup_delay()
    if delay > 0:
        await asyncio.sleep(delay)
    await _run_async(workspace_id, remaining=chain - 1)


def maybe_schedule(*, workspace_id: str, after_stop: bool) -> None:
    """submit 结束后 create_task 投递整理；禁止在 query_loop 的 while 里 await"""
    if not after_stop or not workspace_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _run_safe(workspace_id)
        return
    loop.create_task(_run_async(workspace_id))
