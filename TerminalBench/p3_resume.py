#!/usr/bin/env python3
"""批 3 断点续跑：对比 yaml 全集与已完成的 trial，生成"仅剩任务"的 yaml。

用法: py p3_resume.py <batch_yaml> <jobs_dir> <out_yaml>
逻辑: 读原 yaml 的 datasets[].task_names；扫 jobs_dir 下已完成 trial 的 task 名；
     输出只含未完成任务的同构 yaml（其余字段原样保留）。
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path


def completed_tasks(jobs_dir: str) -> set[str]:
    done: set[str] = set()
    for rj in glob.glob(f"{jobs_dir}/*/*/result.json"):
        try:
            d = json.load(open(rj, encoding="utf-8"))
        except Exception:
            continue
        name = (d.get("task_id") or {}).get("name")
        if name:
            done.add(name)
    return done


def main() -> None:
    src, jobs_dir, out = sys.argv[1], sys.argv[2], sys.argv[3]
    text = Path(src).read_text(encoding="utf-8")
    # 解析 task_names 块
    m = re.search(r"task_names:\n((?:\s+- .+\n)+)", text)
    if not m:
        print("yaml 中未找到 task_names 块")
        sys.exit(2)
    all_tasks = [ln.strip().lstrip("- ").strip() for ln in m.group(1).strip().splitlines()]
    done = completed_tasks(jobs_dir)
    remaining = [t for t in all_tasks if t not in done]
    new_block = "task_names:\n" + "\n".join(f"      - {t}" for t in remaining) + "\n"
    new_text = text[: m.start()] + new_block + text[m.end():]
    Path(out).write_text(new_text, encoding="utf-8")
    print(f"全集 {len(all_tasks)} | 已完成 {len(all_tasks) - len(remaining)} | 剩余 {len(remaining)} → {out}")
    if remaining:
        print("剩余:", ", ".join(t.split('/')[-1] for t in remaining))


if __name__ == "__main__":
    main()
