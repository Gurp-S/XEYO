"""JSONL 随机截断性质测试（种子确定，seed=424242）。

背景：JSONL 读数器出过两族事故（整文件 UnicodeDecodeError 打死读取、截断尾
让 seq/读取语义漂移）。去噪后的契约（2026-10-05 复核）：
- **宽松读者**（``session.record_transcript.load_transcript``）：坏段只报废它
  自己；每个"可解析的非空物理段"都必须出现，顺序不变，且**永不抛**；
- **严格读者**（``engine.action_journal.ActionJournal._latest``）：任一非空
  物理段不可解析/字段非法 → 抛 ``OSError``（不是 UnicodeDecodeError）；
  全部合法 → 全量返回。

参照实现按**字节级物理段**重算期望（尾段允许是无换行的完整行；切点落在任意
字节含多字节字符中间）。断言可证伪：任一不一致即红并带反例。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from engine.action_journal import ActionJournal
from session.record_transcript import load_transcript

_SEED = 424242
_CASES = 120
_ALPHA = [
    "a", "中", "文", "\"", "\\", "\n", "\t", "🙂", "'", "{", "}",
]


def _gen_str(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(_ALPHA) for _ in range(n))


def test_lenient_transcript_reader_survives_random_truncation(tmp_path) -> None:
    rng = random.Random(_SEED)
    fails: list[tuple] = []
    for case in range(_CASES):
        recs = [
            {
                "id": f"p{case}-{i}",
                "text": _gen_str(rng, rng.randint(0, 30)),
                "n": rng.randint(0, 999),
            }
            for i in range(rng.randint(1, 10))
        ]
        data = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs).encode()
        cut = rng.randint(0, len(data))
        path = tmp_path / f"t{case}.jsonl"
        path.write_bytes(data[:cut])

        expected: list[str] = []
        for seg in data[:cut].split(b"\n"):
            if not seg.strip():
                continue
            try:
                obj = json.loads(seg.decode("utf-8"))
            except Exception:
                continue
            if isinstance(obj, dict) and "id" in obj:
                expected.append(obj["id"])

        try:
            rows = load_transcript(path)
        except Exception as e:  # noqa: BLE001
            fails.append((case, "raise", type(e).__name__, cut))
            continue
        got = [r.get("id") for r in rows if isinstance(r, dict)]
        if got != expected:
            fails.append((case, "mismatch", got[:4], expected[:4], cut, len(data)))

    assert not fails, f"截断反例（seed={_SEED}）：{fails[:6]}"


def test_strict_journal_reader_raises_on_any_damaged_segment(tmp_path) -> None:
    rng = random.Random(_SEED + 1)
    fails: list[tuple] = []
    for case in range(_CASES):
        n_rec = rng.randint(1, 10)
        full = [
            {"action_id": f"a{case}-{i}", "status": "completed"} for i in range(n_rec)
        ]
        data = "".join(json.dumps(r) + "\n" for r in full).encode()
        cut = rng.randint(0, len(data))
        journal = ActionJournal("sess_prop", enabled=True, sessions_dir=tmp_path)
        journal.path.parent.mkdir(parents=True, exist_ok=True)
        journal.path.write_bytes(data[:cut])

        segs = data[:cut].split(b"\n")
        broken = False
        for seg in segs:
            if not seg.strip():
                continue
            try:
                obj = json.loads(seg.decode())
            except Exception:
                broken = True
                break
            if not isinstance(obj, dict) or not obj.get("action_id"):
                broken = True
                break

        try:
            got = journal._latest()
        except OSError:
            if not broken:
                fails.append((case, "unexpected-raise", cut))
            continue
        except UnicodeDecodeError:  # noqa: PERF203
            fails.append((case, "unicode-escape", cut))
            continue
        if broken:
            fails.append((case, "missing-raise", cut, len(data)))
            continue
        expect = sum(1 for seg in segs if seg.strip())
        if len(got) != expect:
            fails.append((case, "count", len(got), expect))

    assert not fails, f"严格读者反例（seed={_SEED + 1}）：{fails[:6]}"


def test_reference_classifier_sees_both_classes() -> None:
    """方向控制：分类器必须真能产出『完好』与『损坏』两类样本，否则上面两条空转。

    随机切点几乎必然落在行中（完好类概率≈行数/字节数）——显式两档构造，
    不靠随机碰运气。
    """
    rng = random.Random(_SEED + 2)
    payload = "".join(
        json.dumps({"id": f"x{k}", "v": _gen_str(rng, 15)}) + "\n" for k in range(5)
    ).encode()
    boundaries = [i + 1 for i, b in enumerate(payload) if b == 0x0A]
    assert boundaries, "夹具必须含换行边界"

    def _classify(prefix: bytes) -> bool:
        for seg in prefix.split(b"\n"):
            if not seg.strip():
                continue
            try:
                json.loads(seg.decode("utf-8"))
            except Exception:
                return True
        return False

    intact = [c for c in boundaries if not _classify(payload[:c])]
    mid_cut = boundaries[1] + 3  # 第二行行中（v 串 ≥15 字符，必有 3 字节富余）
    damaged = mid_cut < len(payload) and _classify(payload[:mid_cut])
    assert intact, "行界切点必须判『完好』"
    assert damaged, "行中切点必须判『损坏』"
