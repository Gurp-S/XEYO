"""HumanEval-lite：pass@1 贪心单样本，Windows 兼容子进程执行判分。

表格1对应官方 human-eval；其执行沙箱基于 signal 超时（Unix-only）且不支持
Python 3.14，此处等价复现：数据集仍取 OpenAI 官方 HumanEval.jsonl.gz（164 题），
判分标准与官方一致——补全后拼接测试并要求进程以退出码 0 结束。
偏差：单样本贪心（thinking=enabled），非官方 n=20 温度采样无偏估计。
"""

from __future__ import annotations

import gzip
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
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import DATA_DIR, MODEL_ID, STARTUP_DIR, account, chat, ensure_stdout_utf8  # noqa: E402

RESULTS_DIR = STARTUP_DIR / "humaneval"
SMOKE = bool(os.environ.get("XEYO_EVAL_SMOKE"))
HUMAN_EVAL_URL = (
    "https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz"
)
EXEC_TIMEOUT_S = 20
SYSTEM_PROMPT = (
    "你是 Python 编程专家。请根据给出的函数签名与 docstring 续写出完整实现。"
    "只输出 Python 代码本身：不要解释、不要示例调用、不要输出 markdown 代码块标记。"
)


def fetch_dataset() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / "HumanEval.jsonl.gz"
    if dest.exists() and dest.stat().st_size > 10000:
        return dest
    print(f"[humaneval] downloading {HUMAN_EVAL_URL}")
    req = Request(HUMAN_EVAL_URL, headers={"User-Agent": "xeyo-eval/1.0"})
    with urlopen(req, timeout=120) as resp, dest.open("wb") as sink:
        shutil.copyfileobj(resp, sink)
    print(f"[humaneval] saved -> {dest}")
    return dest


def load_problems() -> list[dict]:
    path = fetch_dataset()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    return rows


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


def run_item(prob: dict, tmp_root: Path) -> dict:
    acc = account("humaneval")
    t0 = time.monotonic()
    item: dict = {"id": prob["task_id"], "pass": False}
    try:
        resp = chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prob["prompt"]},
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
        item.update({"reason": "empty_completion", "finish_reason": resp["finish_reason"], "truncated": resp["truncated"], "latency_s": round(time.monotonic() - t0, 1)})
        return item
    program = (
        prob["prompt"].rstrip()
        + "\n"
        + code
        + "\n"
        + prob["test"].rstrip()
        + f"\ncheck({prob['entry_point']})\n"
    )
    ok, reason = run_python(program, tmp_root)
    item.update(
        {
            "pass": ok,
            "reason": reason,
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
    tmp_root = Path(tempfile.mkdtemp(prefix="humaneval_"))

    problems = load_problems()
    todo_all = problems[:4] if SMOKE else problems
    print(f"[humaneval] model={MODEL_ID} problems={len(todo_all)} smoke={SMOKE}")

    done: set[str] = set()
    if items_path.exists():
        with items_path.open(encoding="utf-8") as f:
            done = {json.loads(x)["id"] for x in f if x.strip()}
    todo = [p for p in todo_all if p["task_id"] not in done]
    print(f"[humaneval] resume: done={len(done)} todo={len(todo)}")

    lock = threading.Lock()
    try:
        with items_path.open("a", encoding="utf-8") as sink:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(run_item, p, tmp_root): p for p in todo}
                for fut in as_completed(futures):
                    r = fut.result()
                    with lock:
                        sink.write(json.dumps(r, ensure_ascii=False) + "\n")
                        sink.flush()
                    status = "PASS" if r["pass"] else f"FAIL({r.get('reason')})"
                    print(f"[humaneval] {r['id']} {status} {r.get('latency_s', '?')}s")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    rows = []
    with items_path.open(encoding="utf-8") as f:
        valid_ids = {p["task_id"] for p in todo_all}
        rows = [json.loads(x) for x in f if x.strip()]
    rows = [r for r in rows if r["id"] in valid_ids]
    passed = sum(1 for r in rows if r["pass"])
    summary = {
        "model": MODEL_ID,
        "thinking": "enabled",
        "protocol": "pass@1 单样本贪心（thinking 开启），子进程退出码判分",
        "problems_total": len(todo_all),
        "evaluated": len(rows),
        "passed": passed,
        "accuracy": round(passed / len(rows), 4) if rows else None,
        "failures_by_reason": _tally([r.get("reason") for r in rows if not r["pass"]]),
        "usage": account("humaneval").summary(),
    }
    out = STARTUP_DIR / "humaneval_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("evaluated", "passed", "accuracy")}, ensure_ascii=False))
    print(f"[humaneval] summary -> {out}")
    return 0


def _tally(seq) -> dict:
    t: dict[str, int] = {}
    for x in seq:
        key = (x or "unknown").split(":")[0][:40]
        t[key] = t.get(key, 0) + 1
    return dict(sorted(t.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
