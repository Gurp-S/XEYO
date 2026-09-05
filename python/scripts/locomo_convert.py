"""LoCoMo-Refined → XEYO 会话 JSONL 转换（确定性/离线，零 LLM）。

用法（在 python/ 下）:
  ..\\python\\.venv\\Scripts\\python.exe -m scripts.locomo_convert --input <数据.jsonl> --outdir "<outdir>"

输入：LoCoMo(-Refined) 每条一行 JSON，含 ``messages`` 数组（role/content），或直接是消息行。
输出：
  - ``<outdir>/loco_<n>.jsonl``：每条对话一个 XEYO 会话文件（role/content/ts）。
  - ``<outdir>/carrier.jsonl``：取最长一条（默认 ≥200 rows）当 A6 真录载体，喂命中率评测。
控制台打印：逐条会话统计表（rows/user_turns）+ 选中的 carrier + ts 唯一性。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _extract_messages(obj):
    """从一行 JSON 抽出消息列表：优先 messages 字段，否则视作单条消息。"""
    if isinstance(obj, dict):
        msgs = obj.get("messages")
        if isinstance(msgs, list):
            return msgs
        if obj.get("role"):
            return [obj]
    return []


def convert(path: Path, outdir: Path, min_rows: int) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    stats = []
    msgs_total = 0
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msgs = _extract_messages(obj)
            if not msgs:
                continue
            role = str(obj.get("role") or "user") if obj.get("role") else "user"
            # 逐条统一为带 ts 的 XEYO 行：role/content/name(可选)/ts(自增秒)
            rows = []
            for j, m in enumerate(msgs):
                if not isinstance(m, dict):
                    continue
                r = {
                    "role": str(m.get("role") or role),
                    "content": m.get("content"),
                    "ts": float(i * 1e3 + j),  # 保持行序唯一，非真实时钟（chat 源无 ts）
                }
                if m.get("name"):
                    r["name"] = m["name"]
                if m.get("tool_call_id"):
                    r["tool_call_id"] = m["tool_call_id"]
                rows.append(r)
            if not rows:
                continue
            msgs_total += len(rows)
            fname = outdir / f"loco_{i}.jsonl"
            with fname.open("w", encoding="utf-8") as fo:
                for r in rows:
                    fo.write(json.dumps(r, ensure_ascii=False) + "\n")
            users = sum(1 for r in rows if r["role"] == "user")
            stats.append({"idx": i, "file": fname, "rows": len(rows), "users": users})

    stats.sort(key=lambda s: s["rows"], reverse=True)
    carrier = None
    for s in stats:
        if s["rows"] >= min_rows:
            carrier = s
            break
    if carrier is None and stats:
        carrier = stats[0]
    if carrier:
        carrier_path = outdir / "carrier.jsonl"
        carrier_path.write_bytes(Path(carrier["file"]).read_bytes())
        carrier["file"] = carrier_path
    ts_unique = 0
    if carrier:
        rows = [json.loads(l) for l in Path(carrier["file"]).read_text(encoding="utf-8").splitlines() if l]
        ts_unique = len({r.get("ts") for r in rows})
    return {"stats": stats, "carrier": carrier, "ts_unique": ts_unique, "msgs_total": msgs_total}


def main() -> int:
    ap = argparse.ArgumentParser(description="LoCoMo-Refined → XEYO 会话 JSONL")
    ap.add_argument("--input", required=True, help="LoCoMo jsonl 路径")
    ap.add_argument("--outdir", default=str(ROOT.parent / ".diag_memory_cost" / "locomo"), help="输出目录")
    ap.add_argument("--min-rows", type=int, default=200, help="carrier 至少多少轮")
    args = ap.parse_args()

    inp = Path(args.input).expanduser()
    if not inp.is_file():
        print(f"[FAIL] 找不到输入: {inp}")
        return 1
    res = convert(inp, Path(args.outdir), args.min_rows)

    print("=" * 72)
    print("LoCoMo → XEYO 会话转换")
    print("=" * 72)
    print(f"  输入: {inp}  消息总数: {res['msgs_total']}  会话数: {len(res['stats'])}")
    print(f"  {'idx':<6}{'rows':>6}{'user_turns':>12}  file")
    for s in res["stats"][:10]:
        print(f"  {s['idx']:<6}{s['rows']:>6}{s['users']:>12}  {s['file'].name}")
    c = res["carrier"]
    if c:
        print("  -" * 36)
        print(f"  [carrier] {c['file']}  rows={c['rows']}  user_turns={c['users']}  ts_unique={res['ts_unique']}")
        flag = "OK" if res["ts_unique"] / max(1, c["rows"]) >= 0.5 else "低(循环副本嫌疑)"
        print(f"  [ts 唯一性] {res['ts_unique']}/{c['rows']} = {res['ts_unique']/max(1,c['rows']):.2f}  -> {flag}")
    else:
        print("  [warn] 没有任何会话达到 min_rows，未生成 carrier。")
    print("[已保存] " + str(Path(args.outdir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
