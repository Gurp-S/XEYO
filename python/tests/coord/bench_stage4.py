"""coord 阶段 4 规模化压测（准入数据源，非 pytest 收集目标）。

多档 worker 数（默认 10/50/100），测四项准入指标（计划 §3 阶段 4）：

1. **吞吐曲线** = merged task/小时 vs agent 数（看每任务协调成本是否随规模增长）；
2. **冲突率** = reconciler reopen / 总收敛（不相交 scope 应≈0）；
3. **漂移** = 无 review 反馈时 reopen 分布（应≈0）；
4. **网关** = ASK suspend 往返延迟 p50/p95。

worker 执行用轻量 work_fn（写 scope 唯一文件，不起真会话——真会话侧已由
test_worker_session 离线 e2e 证闭环）。本测纯压 coord 层（CAS/租约/rebase/
收敛/ASK），隔离协调层的规模天花板。

用法::

    py -3.11 tests/coord/bench_stage4.py [--scale 10,50,100] [--out /path.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # python/

from coord.ask_gate import AskGate  # noqa: E402
from coord.file_store import CoordFileStore  # noqa: E402
from coord.planner import Planner  # noqa: E402
from coord.reconciler import Reconciler  # noqa: E402
from coord.worker_pool import WorkerPool  # noqa: E402
from coord.worktree import git  # noqa: E402


class _NullPresence:
    def touch_busy(self, *a, **k):
        pass

    def clear_owned(self, *a, **k):
        pass


def _mk_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for args in (["init", "-b", "main"], ["config", "user.name", "b"],
                 ["config", "user.email", "b@b"], ["config", "core.autocrlf", "false"]):
        git(repo, *args)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "seed")
    return repo


def _write_fn(rel: str, marker: str):
    def fn(p: Path) -> None:
        (p / rel).write_text(marker, encoding="utf-8")
    return fn


def bench_scale(tmp: Path, n: int) -> dict:
    repo = _mk_repo(tmp / f"scale_{n}")  # 每档独立 repo，基线一致（单 seed commit）
    store = CoordFileStore(repo)
    root = str(repo)

    planner = Planner(repo, store)
    specs = [{"title": f"b{i}", "scope": [f"bench_{i}.txt"], "brief": "x"}
             for i in range(n)]
    planner.plan_round(specs, goal_id=f"bench_{n}")

    errors: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        pool = WorkerPool(repo, CoordFileStore(repo))
        wid = f"benchw{i}"
        base = git(repo, "rev-parse", "main").stdout.strip()
        t = planner.claim_next(root=root, worker_id=wid, base_commit=base)
        if t is None:
            with lock:
                errors.append(f"worker{i}:claim_none")
            return
        out = pool.run_task(t.task_id, wid, _write_fn(t.scope[0], f"c:{t.task_id}"))
        if not out.ok:
            with lock:
                errors.append(f"worker{i}:{out.error}")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(16, n)) as ex:
        list(ex.map(worker, range(n)))
    t_run = time.perf_counter() - t0

    rec = Reconciler(repo, store)
    t1 = time.perf_counter()
    report = rec.reconcile_ready()
    t_rec = time.perf_counter() - t1

    merged = len(report["merged"])
    reopened = len(report["reopened"])
    blocked = len(report["blocked"])
    total = merged + reopened + blocked

    lines = git(repo, "rev-list", "--parents", "main").stdout.strip().splitlines()
    linear = all(len(l.split()) == 2 for l in lines[:-1])
    content_ok = sum(
        1 for i in range(n)
        if git(repo, "cat-file", "-e", f"main:bench_{i}.txt", check=False).returncode == 0
    )
    assert not (repo / ".git" / "index.lock").exists(), "index.lock leaked"

    return {
        "scale": n,
        "run_wall_s": round(t_run, 3),
        "reconcile_wall_s": round(t_rec, 3),
        "reconcile_per_task_s": round(t_rec / merged, 4) if merged else None,
        "throughput_tasks_per_hour": round(merged / t_rec * 3600.0, 1) if merged and t_rec > 0 else None,
        "merged": merged, "reopened": reopened, "blocked": blocked,
        "conflict_rate": round((reopened / total) if total else 0.0, 4),
        "claim_errors": errors[:3],
        "main_commits": len(lines), "main_linear": linear,
        "content_ok": content_ok, "content_total": n,
    }


def bench_ask(tmp: Path, n: int) -> dict:
    repo = _mk_repo(tmp / "ask")
    store = CoordFileStore(repo)
    root = str(repo)
    planner = Planner(repo, store)
    ids = planner.plan_round(
        [{"title": f"a{i}", "scope": [f"ask_{i}.txt"]} for i in range(n)])["created"]
    gate = AskGate(repo, store, presence=_NullPresence(), ttl=1e9)
    lat: list[float] = []
    for tid in ids:
        base = git(repo, "rev-parse", "main").stdout.strip()
        wid = f"aw{tid[-5:]}"
        store.acquire_scope(root, wid, [f"ask_{ids.index(tid)}.txt"])
        store.claim_task(tid, wid, base)
        t0 = time.perf_counter()
        gate.suspend(root=root, task_id=tid, worker_id=wid, kind="bench", payload=".")
        lat.append((time.perf_counter() - t0) * 1000.0)
    ts = sorted(lat)
    return {"scale": n,
            "suspend_p50_ms": round(ts[len(ts) // 2], 2),
            "suspend_p95_ms": round(ts[min(int(len(ts) * 0.95), len(ts) - 1)], 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", default="10,50,100")
    ap.add_argument("--out", default="")
    ap.add_argument("--ask-samples", type=int, default=40)
    args = ap.parse_args()
    scales = [int(s) for s in args.scale.split(",") if s.strip()]

    tmp = Path(tempfile.mkdtemp(prefix="coord-bench-"))
    out = {"env": {"python": sys.version.split()[0], "os": sys.platform, "tmp": str(tmp)},
           "throughput": [], "ask_gate": {}}
    for n in scales:
        r = bench_scale(tmp, n)
        out["throughput"].append(r)
        print(f"scale={n:>4}  merged={r['merged']:>4}  reopen={r['reopened']}  "
              f"blocked={r['blocked']}  linear={r['main_linear']}  "
              f"reconcile/task={r['reconcile_per_task_s']}s  "
              f"content={r['content_ok']}/{n}  thr={r['throughput_tasks_per_hour']}/h")

    ag = bench_ask(tmp, args.ask_samples)
    out["ask_gate"] = ag
    print(f"ask_gate  suspend p50={ag['suspend_p50_ms']}ms p95={ag['suspend_p95_ms']}ms "
          f"(n={args.ask_samples})")

    rpr = [x["reconcile_per_task_s"] for x in out["throughput"] if x["reconcile_per_task_s"]]
    if len(rpr) >= 2:
        out["scaling"] = {
            "reconcile_per_task_first": rpr[0],
            "reconcile_per_task_last": rpr[-1],
            "ratio_last_over_first": round(rpr[-1] / rpr[0], 3),
            "note": "≈1 = 每任务协调成本不随规模增长(线性);>2 = 超线性衰减",
        }
        print("scaling:", json.dumps(out["scaling"], ensure_ascii=False))

    path = args.out or str(tmp / "coord-stage4-bench.json")
    Path(path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
