"""coord 阶段 0 离线收益探针（旁路验证，非 pytest 收集目标）。

对照两个后端在「双独立进程」下的行为差异：

- ``memory``（现状默认）: 进程内状态，跨进程零可见 → 交叉检测 0 命中；
- ``file``（coord 旁路）: 跨进程文件共享 → 交叉检测命中。

场景：
  A  presence 交叉写检测（各自 note_write 后查对方文件归属）
  B  跨进程通知投递（A 进程 queue_notice → B 进程 take_notices）
  C  延迟微基准（note_write / touch_busy / owner_of 的 p50/p95，file vs memory）

用法::

    py -3.11 tests/coord/benefit_probe.py          # 父模式，stdout 输出汇总 JSON
    py -3.11 tests/coord/benefit_probe.py --child ...   # 子进程模式（内部使用）

子进程模式 stdout 只放单行 JSON，诊断走 stderr。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # python/

ROUNDS = 25
BENCH_OPS = 150


def _presence(backend: str):
    """backend → presence 对象。file 走 XEYO_HOME 隔离索引，memory 为进程内状态。"""
    if backend == "file":
        from coord.presence_adapter import FileBackedPresence

        return FileBackedPresence()
    from engine.session_presence import SessionPresenceRegistry

    return SessionPresenceRegistry()


# -- 子进程模式 -------------------------------------------------------------

def _child(argv: list[str]) -> int:
    mode = argv[2]
    if mode == "note":
        _, backend, ws, sid, rel = argv[2], argv[3], argv[4], argv[5], argv[6]
        p = _presence(backend)
        p.note_write(ws, sid, str(Path(ws) / rel))
        print(json.dumps({"ok": True}))
        return 0

    if mode == "probe":
        _, backend, ws, sid_self, rel_other, sid_other = (
            argv[2], argv[3], argv[4], argv[5], argv[6], argv[7],
        )
        p = _presence(backend)
        entry = p.owner_of(ws, str(Path(ws) / rel_other), exclude_session=sid_self)
        print(json.dumps({"seen": entry is not None, "by": entry.session_id if entry else None}))
        return 0

    if mode == "notify":
        _, backend, ws, sid_self, sid_other = argv[2], argv[3], argv[4], argv[5], argv[6]
        p = _presence(backend)
        p.note_write(ws, sid_self, str(Path(ws) / f"{sid_self}.py"))
        p.queue_notice(sid_other, f"peer {sid_self} touched shared file")
        print(json.dumps({"queued": True}))
        return 0

    if mode == "take":
        _, backend, ws, sid = argv[2], argv[3], argv[4], argv[5]
        p = _presence(backend)
        got = p.take_notices(sid)
        print(json.dumps({"got": got}))
        return 0

    if mode == "bench":
        _, backend, ws, sid = argv[2], argv[3], argv[4], argv[5]
        p = _presence(backend)
        n = BENCH_OPS
        out: dict[str, dict[str, float]] = {}
        for opname, fn in (
            ("note_write", lambda i: p.note_write(ws, sid, str(Path(ws) / f"bench-{i}.py"))),
            ("touch_busy", lambda i: p.touch_busy(ws, sid, busy=bool(i % 2), title=f"t{i}")),
            ("owner_of", lambda i: p.owner_of(ws, str(Path(ws) / f"bench-{i}.py"), exclude_session=sid)),
        ):
            samples: list[float] = []
            for i in range(n):
                t0 = time.perf_counter_ns()
                fn(i)
                samples.append((time.perf_counter_ns() - t0) / 1000.0)  # us
            s = sorted(samples)
            out[opname] = {
                "n": n,
                "p50_us": round(s[n // 2], 1),
                "p95_us": round(s[int(n * 0.95)], 1),
                "mean_us": round(sum(s) / n, 1),
            }
        print(json.dumps({"backend": backend, "ops": out}))
        return 0

    print(json.dumps({"error": f"unknown child mode {mode}"}))
    return 2


def _spawn(mode: str, backend: str, ws: str, global_home: str, *args: str) -> dict:
    env = dict(os.environ)
    if backend == "file":
        env["XEYO_HOME"] = global_home
    else:
        env.pop("XEYO_HOME", None)
    r = subprocess.run(
        [sys.executable, __file__, "--child", mode, backend, ws, *args],
        capture_output=True, text=True, env=env, timeout=60,
    )
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {"error": r.stdout[-200:], "stderr": r.stderr[-300:]}


# -- 父模式 ------------------------------------------------------------------

def _pct_summary(vals: list[dict], backend: str) -> dict:
    """backend 的 ops 摘要直接来自子进程 JSON。"""
    for v in vals:
        if v.get("backend") == backend:
            return v.get("ops", {})
    return {}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="coord-benefit-"))
    ws = str(tmp / "ws")
    global_home = str(tmp / "global")
    Path(ws).mkdir(parents=True, exist_ok=True)
    Path(global_home).mkdir(parents=True, exist_ok=True)

    # -- 场景 A: presence 交叉写检测 ------------------------------------
    probes = hits_file = hits_mem = 0
    for i in range(ROUNDS):
        rel_a, rel_b = f"a{i}.py", f"b{i}.py"
        # 第一步：两个进程各自 note 自己的文件（并发，全部完成再探测）
        pa = subprocess.Popen([sys.executable, __file__, "--child", "note", "file", ws, "sA", rel_a],
                              stdout=subprocess.DEVNULL)
        pb = subprocess.Popen([sys.executable, __file__, "--child", "note", "file", ws, "sB", rel_b],
                              stdout=subprocess.DEVNULL)
        ma = subprocess.Popen([sys.executable, __file__, "--child", "note", "memory", ws, "sA", rel_a],
                              stdout=subprocess.DEVNULL)
        mb = subprocess.Popen([sys.executable, __file__, "--child", "note", "memory", ws, "sB", rel_b],
                              stdout=subprocess.DEVNULL)
        for p in (pa, pb, ma, mb):
            p.wait(timeout=60)
        # 第二步：各自探测对方文件
        fa = _spawn("probe", "file", ws, global_home, "sA", rel_b, "sB")
        fb = _spawn("probe", "file", ws, global_home, "sB", rel_a, "sA")
        ma2 = _spawn("probe", "memory", ws, global_home, "sA", rel_b, "sB")
        mb2 = _spawn("probe", "memory", ws, global_home, "sB", rel_a, "sA")
        probes += 2
        hits_file += int(bool(fa.get("seen"))) + int(bool(fb.get("seen")))
        hits_mem += int(bool(ma2.get("seen"))) + int(bool(mb2.get("seen")))

    cross = {
        "rounds": ROUNDS,
        "file": {"probes": probes, "hits": hits_file, "rate": round(hits_file / probes, 3)},
        "memory": {"probes": probes, "hits": hits_mem, "rate": round(hits_mem / probes, 3)},
    }

    # -- 场景 B: 跨进程通知投递 -----------------------------------------
    d_file = d_mem = 0
    for i in range(ROUNDS):
        # sB 先登记（queue_notice 反查索引需要），再由 A 进程投递
        _spawn("note", "file", ws, global_home, "sB", f"n{i}.py")
        _spawn("note", "memory", ws, global_home, "sB", f"n{i}.py")
        _spawn("notify", "file", ws, global_home, "sA", "sB")
        _spawn("notify", "memory", ws, global_home, "sA", "sB")
        tf = _spawn("take", "file", ws, global_home, "sB")
        tm = _spawn("take", "memory", ws, global_home, "sB")
        d_file += int(bool(tf.get("got")))
        d_mem += int(bool(tm.get("got")))

    notices = {
        "rounds": ROUNDS,
        "file": {"delivered": d_file, "rate": round(d_file / ROUNDS, 3)},
        "memory": {"delivered": d_mem, "rate": round(d_mem / ROUNDS, 3)},
    }

    # -- 场景 C: 延迟微基准 ----------------------------------------------
    bf = _spawn("bench", "file", ws, global_home, "sA")
    bm = _spawn("bench", "memory", ws, global_home, "sA")
    latency = {"file": bf.get("ops", {}), "memory": bm.get("ops", {})}

    report = {
        "cross_detection": cross,
        "notice_delivery": notices,
        "latency": latency,
        "env": {
            "python": sys.version.split()[0],
            "os": sys.platform,
            "rounds": ROUNDS,
            "bench_ops": BENCH_OPS,
            "tmp": str(tmp),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        raise SystemExit(_child(sys.argv))
    raise SystemExit(main())
