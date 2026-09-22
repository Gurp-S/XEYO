"""问答集语料解析（评测旁路）：把「仓内真实会话 + 外部真值」变成可吃样本。

两条来源，**共同点是都要带外部真值或显式声明没有**：

1. ``TerminalBench/evidence/<batch>/<run>/trials/<task>__<id>/``
   真实 XEYO ``session.jsonl`` + ``verifier/reward.txt``（任务自带 verifier = 外部 ground truth）
   + ``result.json``（task_checksum / exception_info）。
2. 任意目录下的 ``*.jsonl``（如历史 ``codex_holdout_v1``）：**没有外部真值**，
   ``reward=None`` —— 用它出的数只能当调试线索，报告里会显式标注 ``no_external_truth``。

纪律：
- 离线、零 API、零网络；文件哈希进 manifest，报告头带 manifest 指纹（不可复现即拒绝出数）。
- **fail-open**：语料缺失/不可解析 ⇒ 返回空列表并记 ``corpus_missing``，绝不静默当成满分，
  也绝不因为读不到真值就把样本算「通过」。
- 语料本体在 ``.gitignore`` 内（``TerminalBench/``、``_wsc_out/``）⇒ 入库的只有 manifest。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = REPO_ROOT / "TerminalBench" / "evidence"
LEGACY_CODEX = Path(r"D:\lea\XEYO-wsc-task-ab-v1\_wsc_out\codex_holdout_v1")
BATTERY = REPO_ROOT / "_wsc_out" / "wsc_task_battery_v1.json"


@dataclass
class Session:
    """一条会话：消息 + 身份 + 外部真值 + 指纹。"""

    sid: str
    path: Path
    sha256: str
    messages: tuple[dict, ...] = ()
    reward: str | None = None
    shape: str = "unknown"
    task: str = ""
    batch: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def has_truth(self) -> bool:
        return self.reward is not None

    def row(self) -> dict:
        return {"sid": self.sid, "task": self.task, "shape": self.shape, "batch": self.batch,
                "reward": self.reward, "sha256": self.sha256, "messages": len(self.messages),
                "path": str(self.path)}


def digest_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:16]


def digest_file(path: Path) -> str:
    try:
        return digest_bytes(path.read_bytes())
    except OSError:
        return ""


def load_jsonl(path: Path) -> list[dict]:
    """逐行 JSON 解析；坏行跳过（语料是外部产物，不允许它把整次判定打断）。"""
    out: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _shapes() -> dict[str, str]:
    """任务 → shape（来自 ``wsc_task_battery_v1.json``）；读不到就空表（fail-open）。"""
    out: dict[str, str] = {}
    try:
        battery = json.loads(BATTERY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for task in battery.get("tasks") or ():
        if isinstance(task, dict) and task.get("id"):
            out[str(task["id"])] = str(task.get("shape") or "unknown")
    return out


def _reward_of(trial: Path) -> tuple[str | None, list[str]]:
    """外部真值：``verifier/reward.txt`` 为准；缺失即 ``None``（**不猜、不折算**）。"""
    notes: list[str] = []
    cand = trial / "verifier" / "reward.txt"
    if cand.exists():
        try:
            return cand.read_text(encoding="utf-8", errors="replace").strip()[:40], notes
        except OSError:
            notes.append("reward_unreadable")
            return None, notes
    rj = trial / "result.json"
    if rj.exists():
        try:
            payload = json.loads(rj.read_text(encoding="utf-8", errors="replace"))
            exc = (payload.get("exception_info") or {})
            if isinstance(exc, dict) and exc.get("exception_type"):
                notes.append(f"exception={exc['exception_type']}")
        except (OSError, ValueError):
            pass
    notes.append("no_reward_file")
    return None, notes


def resolve_evidence(root: Path = DEFAULT_EVIDENCE, *, limit: int | None = None,
                     batches: tuple[str, ...] = ()) -> list[Session]:
    """``TerminalBench/evidence`` 三批次：真实会话 + verifier 真值。"""
    out: list[Session] = []
    shapes = _shapes()
    if not root.exists():
        return out
    for batch in sorted(p for p in root.iterdir() if p.is_dir()):
        if batches and batch.name not in batches:
            continue
        for trial in sorted(batch.glob("*/trials/*")):
            sess = trial / "session.jsonl"
            if not sess.exists():
                continue
            msgs = load_jsonl(sess)
            if not msgs:
                continue
            reward, notes = _reward_of(trial)
            task = trial.name.split("__", 1)[0]
            out.append(Session(sid=f"{batch.name}/{trial.name}", path=sess,
                               sha256=digest_file(sess), messages=tuple(msgs), reward=reward,
                               shape=shapes.get(task, "unknown"), task=task, batch=batch.name,
                               notes=notes))
            if limit and len(out) >= limit:
                return out
    return out


def resolve_jsonl_dir(root: Path = LEGACY_CODEX, *, limit: int | None = None) -> list[Session]:
    """历史 *.jsonl 语料（无外部真值 ⇒ ``reward=None``，报告显式标 ``no_external_truth``）。"""
    out: list[Session] = []
    if not root.exists():
        return out
    for f in sorted(root.glob("*.jsonl")):
        msgs = load_jsonl(f)
        if not msgs:
            continue
        out.append(Session(sid=f.stem, path=f, sha256=digest_file(f), messages=tuple(msgs),
                           reward=None, task=f.stem, batch="legacy", notes=["no_external_truth"]))
        if limit and len(out) >= limit:
            return out
    return out


def manifest(sessions: list[Session]) -> dict:
    """语料清单（入库形态）：相对路径 + sha256 + 外部真值 + shape。"""
    rows = []
    truth = 0
    for s in sessions:
        try:
            rel = str(s.path.relative_to(REPO_ROOT))
        except ValueError:
            rel = str(s.path)
        truth += int(s.has_truth)
        rows.append({"sid": s.sid, "path": rel, "sha256": s.sha256, "reward": s.reward,
                     "shape": s.shape, "messages": len(s.messages), "notes": s.notes})
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"sessions": len(rows), "with_external_truth": truth, "rows": rows,
            "digest": digest_bytes(blob)}


__all__ = ["BATTERY", "DEFAULT_EVIDENCE", "LEGACY_CODEX", "REPO_ROOT", "Session",
           "digest_bytes", "digest_file", "load_jsonl", "manifest", "resolve_evidence",
           "resolve_jsonl_dir"]
