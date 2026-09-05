"""MBPP-lite：sanitized 子集（task_id 排序前 100 题）pass@1，本地执行判分。

表格1对应 HuggingFace `google-research-datasets/mbpp`；huggingface.co 不可直连时
自动走 hf-mirror.com 镜像。提示词只放前 3 条断言（官方常见做法），判分用全量
test_list 断言：生成代码拼接全部断言后要求进程退出码为 0。
思考模式：按表格2「代码生成 → 开启」。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import DATA_DIR, MODEL_ID, STARTUP_DIR, account, chat, ensure_stdout_utf8  # noqa: E402

RESULTS_DIR = STARTUP_DIR / "mbpp"
SMOKE = bool(os.environ.get("XEYO_EVAL_SMOKE"))
N_SAMPLES = int(os.environ.get("XEYO_EVAL_MBPP_N", "100"))
MIRROR_PREFIX = "https://hf-mirror.com/datasets/google-research-datasets/mbpp/resolve/main"
PARQUETS = [
    "sanitized/train-00000-of-00001.parquet",
    "sanitized/validation-00000-of-00001.parquet",
    "sanitized/test-00000-of-00001.parquet",
]
EXEC_TIMEOUT_S = 20
SYSTEM_PROMPT = (
    "你是 Python 编程专家。根据任务描述写出完整 Python 代码（含必要的 import）。"
    "代码必须能通过给出的测试断言。只输出 Python 代码本身：不要解释、不要 markdown 代码块标记。"
)


def fetch_dataset() -> list[dict]:
    dest_dir = DATA_DIR / "mbpp"
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for rel in PARQUETS:
        dest = dest_dir / Path(rel).name
        if not (dest.exists() and dest.stat().st_size > 1000):
            url = f"{MIRROR_PREFIX}/{rel}"
            print(f"[mbpp] downloading {url}")
            import urllib.request

            with urllib.request.urlopen(url, timeout=120) as resp:
                dest.write_bytes(resp.read())
        paths.append(dest)
    rows = _read_rows(paths)
    rows.sort(key=lambda r: str(r.get("task_id") or ""))
    rows = rows[:N_SAMPLES]
    # 归一化 list 字段（pyarrow/pandas 可能返回 ndarray）
    for r in rows:
        r["test_list"] = [str(x) for x in _aslist(r.get("test_list"))]
        r["test_imports"] = [str(x) for x in _aslist(r.get("test_imports"))]
    return rows


def _read_rows(paths: list[Path]) -> list[dict]:
    """读取 parquet 为 list[dict]，尽量不依赖 pandas。

    优先 pyarrow（轻量，`to_pylist` 无需 pandas）；其次才回退 pandas；都没装则给出明确报错。
    不再在模块顶层 import pandas，避免 `import mbpp_lite` 因缺 pandas 直接报错。
    """
    try:
        import pyarrow.parquet as pq
    except ImportError:
        pq = None
    if pq is not None:
        out: list[dict] = []
        for p in paths:
            out.extend(pq.read_table(p).to_pylist())
        return out

    try:
        import pandas as pd
    except ImportError:
        pd = None
    if pd is not None:
        frames = [pd.read_parquet(p) for p in paths]
        df = pd.concat(frames, ignore_index=True)
        return df.to_dict("records")

    raise RuntimeError(
        "读取 MBPP parquet 需要 pyarrow 或 pandas。请先安装（推荐轻量 pyarrow）："
        "`pip install pyarrow`。"
    )


def _aslist(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    tolist = getattr(v, "tolist", None)
    return tolist() if callable(tolist) else [v]


def extract_code(text: str | None) -> str:
    text = text or ""
    blocks = re.findall(r"```(?:python|py)?[ \t]*\r?\n(.*?)```", text, re.S)
    if blocks:
        return "\n\n".join(b.strip("\r\n") for b in blocks).strip()
    return text.strip()


def run_python(program: str, tmp_root: Path) -> tuple[bool, str]:
    d = Path(tempfile.mkdtemp(dir=tmp_root))
    script = d / "sample.py"
    script.write_text(program, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=EXEC_TIMEOUT_S,
            cwd=str(d),
        )
        if proc.returncode == 0:
            return True, "ok"
        tail = (proc.stderr or "").strip().splitlines()
        return False, tail[-1][:200] if tail else f"exit={proc.returncode}"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def run_item(row: dict, tmp_root: Path) -> dict:
    acc = account("mbpp")
    t0 = time.monotonic()
    tid = f"task_{row['task_id']}"
    item: dict = {"id": tid, "pass": False}
    prompt_tests = "\n".join(row["test_list"][:3])
    user = (
        f"{row['prompt']}\n\n你的代码需要通过以下测试：\n{prompt_tests}\n\n"
        "请给出完整可运行的 Python 函数实现。"
    )
    try:
        resp = chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            thinking="enabled",
            max_tokens=4096,
            acct=acc,
        )
    except Exception as e:  # noqa: BLE001
        item.update({"reason": "api_error", "detail": str(e)[:200], "latency_s": round(time.monotonic() - t0, 1)})
        return item
    code = extract_code(resp["content"])
    if not code:
        item.update({"reason": "empty_completion", "finish_reason": resp["finish_reason"], "latency_s": round(time.monotonic() - t0, 1)})
        return item
    program = (
        code
        + ("\n" + "\n".join(row["test_imports"]) if row["test_imports"] else "")
        + "\n"
        + "\n".join(row["test_list"])
        + "\n"
    )
    ok, reason = run_python(program, tmp_root)
    item.update(
        {
            "pass": ok,
            "reason": reason.split(":")[0][:40],
            "truncated": resp["truncated"],
            "reasoning_chars": resp["reasoning_chars"],
            "latency_s": round(time.monotonic() - t0, 1),
        }
    )
    return item


def main() -> int:
    ensure_stdout_utf8()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    items_path = RESULTS_DIR / "items.jsonl"
    tmp_root = Path(tempfile.mkdtemp(prefix="mbpp_"))

    rows = fetch_dataset()
    todo_all = rows[:4] if SMOKE else rows
    print(f"[mbpp] model={MODEL_ID} samples={len(todo_all)} smoke={SMOKE}")

    done: set[str] = set()
    if items_path.exists():
        with items_path.open(encoding="utf-8") as f:
            done = {json.loads(x)["id"] for x in f if x.strip()}
    todo = [r for r in todo_all if f"task_{r['task_id']}" not in done]
    print(f"[mbpp] resume: done={len(done)} todo={len(todo)}")

    lock = threading.Lock()
    try:
        with items_path.open("a", encoding="utf-8") as sink:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(run_item, r, tmp_root): r for r in todo}
                for fut in as_completed(futures):
                    r = fut.result()
                    with lock:
                        sink.write(json.dumps(r, ensure_ascii=False) + "\n")
                        sink.flush()
                    status = "PASS" if r["pass"] else f"FAIL({r.get('reason')})"
                    print(f"[mbpp] {r['id']} {status} {r.get('latency_s', '?')}s")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    valid_ids = {f"task_{r['task_id']}" for r in todo_all}
    with items_path.open(encoding="utf-8") as f:
        allrows = [json.loads(x) for x in f if x.strip()]
    merged = [r for r in allrows if r["id"] in valid_ids]
    passed = sum(1 for r in merged if r["pass"])
    summary = {
        "model": MODEL_ID,
        "thinking": "enabled",
        "protocol": "pass@1 单样本贪心（thinking 开启），prompt 含 3 条示例断言，全量 test_list 判分",
        "samples_total": len(todo_all),
        "evaluated": len(merged),
        "passed": passed,
        "accuracy": round(passed / len(merged), 4) if merged else None,
        "failures_by_reason": _tally([r.get("reason") for r in merged if not r["pass"]]),
        "usage": account("mbpp").summary(),
    }
    out = STARTUP_DIR / "mbpp_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("evaluated", "passed", "accuracy")}, ensure_ascii=False))
    print(f"[mbpp] summary -> {out}")
    return 0


def _tally(seq) -> dict:
    t: dict[str, int] = {}
    for x in seq:
        key = (x or "unknown").split(":")[0][:40]
        t[key] = t.get(key, 0) + 1
    return dict(sorted(t.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
