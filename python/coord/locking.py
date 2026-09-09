"""资源级跨进程文件锁：O_EXCL 原子获取 + mtime stale 回收。

与 ``engine/workspace_lock.py`` 的差异：该锁绑定整个 workspace 且含心跳线程，
适合"长持有"；coord 的临界区是毫秒级读-改-写，资源粒度细（每个状态文件一把锁），
无心跳、纯 mtime 判 stale（持有远小于 ttl 即安全）。降级铁律同 goal_state：
锁竞争超时 → 调用方降级（当次操作仍执行，仅放弃跨进程互斥/持久化），不挡主路径。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path

_log = logging.getLogger("xeyo.coord.lock")

DEFAULT_TTL_SEC = 10.0
DEFAULT_TIMEOUT_SEC = 5.0
_SPIN_SEC = 0.01


class FileGuard:
    """单文件互斥。用法::

        with FileGuard(path) as ok:
            if ok:
                ... 临界区 ...
            else:
                ... 降级路径 ...
    """

    def __init__(self, path: str | Path, *, ttl: float = DEFAULT_TTL_SEC,
                 timeout: float = DEFAULT_TIMEOUT_SEC) -> None:
        self.path = Path(path)
        self.ttl = float(ttl)
        self.timeout = float(timeout)
        self._token: str | None = None

    def _stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return False
        except OSError:
            return False
        return age >= self.ttl

    def _try_create(self) -> bool:
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        except FileNotFoundError:
            # 锁目录缺失：先建目录再试一次。
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except OSError:
                return False
        except OSError:
            return False
        with os.fdopen(fd, "wb") as handle:
            handle.write(self._token.encode("utf-8"))
        return True

    def __enter__(self) -> bool:
        self._token = uuid.uuid4().hex
        deadline = time.monotonic() + self.timeout
        while True:
            if self._stale():
                try:
                    self.path.unlink()
                except OSError:
                    pass
            if self._try_create():
                return True
            if time.monotonic() >= deadline:
                _log.debug("coord lock timeout at %s (degrading)", self.path)
                self._token = None
                return False
            time.sleep(_SPIN_SEC)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is None:
            return
        try:
            data = self.path.read_bytes()
        except OSError:
            data = b""
        # 只删自己的锁：stale 回收者/新持有者不受影响。
        if data.strip().decode("utf-8", errors="ignore") == self._token:
            try:
                self.path.unlink()
            except OSError:
                pass
        self._token = None


__all__ = ["FileGuard"]
