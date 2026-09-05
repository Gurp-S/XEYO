"""LoCoMo-offline 汇总报告：从 XEYO_USAGE_DIR ledger 读成本/命中，从 quality_validation.json 读 hitrate 表行。

用法（在 python/ 下）:
  ..\\python\\.venv\\Scripts\\python.exe -m scripts.locomo_report --usage "<usage_dir>" [--quality "<json>"]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _agg_usage(usage_dir: Path) -> dict:
    events: list[dict] = []
    p = usage_dir / "events.jsonl"
    if p.is_file():
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not events:
        return {"exists": False}
    req = len(events)
    prompt = hit = miss = out = 0
    cost = 0.0
    by_model: dict[str, dict] = {}
    for ev in events:
        prompt += int(ev.get("prompt_tokens") or 0)
        h = int(ev.get("cache_hit") or 0)
        m = int(ev.get("cache_miss") or 0)
        hit += h
        miss += m
        out += int(ev.get("output") or 0)
        cost += float(ev.get("cost_cny") or 0)
        key = str(ev.get("model") or "unknown")
        b = by_model.setdefault(key, {"req": 0, "hit": 0, "miss": 0, "output": 0, "cost": 0.0})
        b["req"] += 1
        b["hit"] += h
        b["miss"] += m
        b["output"] += int(ev.get("output") or 0)
        b["cost"] += float(ev.get("cost_cny") or 0)
    total_in = hit + miss
    return {
        "exists": True,
        "req": req,
        "prompt": prompt,
        "hit": hit,
        "miss": miss,
        "output": out,
        "cost": round(cost, 6),
        "hit_rate": round(hit / total_in, 4) if total_in else 0.0,
        "by_model": by_model,
    }


def _agg_quality(quality_path: Path, prefix: str = "hitrate_") -> list[dict]:
    if not quality_path.is_file():
        return []
    try:
        data = json.loads(quality_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    rows = data.get("rows") or {}
    out: list[dict] = []
    for cid, r in rows.items():
        if cid.startswith(prefix) or cid.startswith("deploy_project_mode_"):
            det = r.get("detail") or {}
            out.append({
                "id": cid,
                "input": det.get("hit_rate"),
                "hit_rate": det.get("hit_rate"),
                "input_tokens": r.get("input_tokens"),
                "action": r.get("action"),
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="LoCoMo-offline 汇总报告")
    ap.add_argument("--usage", help="XEYO_USAGE_DIR（读 events.jsonl 汇总成本）")
    ap.add_argument("--quality", help="quality_validation.json（读 hitrate 表行）")
    args = ap.parse_args()

    print("=" * 72)
    print("LoCoMo 结果汇总")
    print("=" * 72)

    if args.usage:
        u = _agg_usage(Path(args.usage))
        if not u["exists"]:
            print("[usage] ledger 无数据（未产生事件）")
        else:
            print(f"[usage] 请求={u['req']}  输入={u['prompt']}  hits={u['hit']} miss={u['miss']} 输出={u['output']}")
            print(f"[usage] 缓存命中率={u['hit_rate'] * 100:.2f}%  累计成本=¥{u['cost']:.4f}")
            for mk, m in sorted(u["by_model"].items(), key=lambda kv: -kv[1]["cost"]):
                t = int(m["hit"]) + int(m["miss"])
                hr = float(m["hit"]) / t if t else 0.0
                print(f"    {mk}: req={m['req']} 命中={hr * 100:.1f}% cost=¥{m['cost']:.4f}")

    if args.quality:
        rows = _agg_quality(Path(args.quality))
        if not rows:
            print("[quality] 无 hitrate/deploy 行")
        for r in rows:
            hr = r.get("hit_rate")
            print(f"[quality] {r['id']}: hit_rate={hr} input_tokens={r.get('input_tokens')} action={r.get('action')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
