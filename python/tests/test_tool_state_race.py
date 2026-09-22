"""并发竞态回归：共享状态表「遍历中被写」不得抛 RuntimeError。

2026-09-20 实测：一次只读目录列举被工具层判 fail-closed——
``tool error: RuntimeError: dictionary changed size during iteration``，
真实输出全丢（整次调用白跑）。成因只能是遍历某张进程级共享 dict 的同时，
另一个执行流（同一批 tool_use 的并发兄弟，或后台回调线程）在写它。
``ReadFileState`` 是其中一张：Read/Glob/Grep/Bash 路由都会登记。

本文件用"写线程 + 读线程"把竞态放大到确定性：修好之前必红。
"""

from __future__ import annotations

import threading

from tools.fileio.read_state import FileStateEntry, ReadFileState


def test_snapshot_meta_survives_concurrent_mutation() -> None:
    store = ReadFileState(max_entries=64)
    stop = threading.Event()

    def writer() -> None:
        i = 0
        while not stop.is_set():
            store.set(f"p{i}.py", FileStateEntry(content="x", timestamp=i))
            i += 1
            if i % 16 == 0:
                store.clear()  # 强制容量涨落（"字典大小变化"正是报错条件）

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        for _ in range(3_000):
            snapshot = store.snapshot_meta()
            assert isinstance(snapshot, dict)
    finally:
        stop.set()
        thread.join(timeout=5)


def test_get_and_set_survive_concurrent_writers() -> None:
    store = ReadFileState(max_entries=32)
    stop = threading.Event()
    errors: list[BaseException] = []

    def writer(tag: int) -> None:
        i = 0
        try:
            while not stop.is_set():
                store.set(f"c{tag}_{i % 24}.py", FileStateEntry(content="x", timestamp=i))
                store.get(f"c{tag}_{i % 24}.py")
                i += 1
        except BaseException as exc:  # noqa: BLE001 — 竞态异常需回传主线程断言
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,), daemon=True) for t in range(4)]
    for thread in threads:
        thread.start()
    try:
        for _ in range(1_500):
            store.snapshot_meta()
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
    assert not errors, f"并发读写抛出异常：{errors!r}"
