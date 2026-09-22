"""WSC V2 (Canonical Working State) —— Phase 1 shadow-only 层。

生产默认仍是 V1。`XEYO_WSC_IMPL` 只允许 `v1|v2|shadow`，默认 `v1`；
本包的 `project()` 在 v1 档下**不被生产调用**，且任何档位都不返回替代 V1 的输出。
"""

from __future__ import annotations

import os
from typing import Literal

Impl = Literal["v1", "v2", "shadow"]

_VALID = ("v1", "v2", "shadow")


def impl() -> Impl:
    raw = (os.environ.get("XEYO_WSC_IMPL") or "v1").strip().lower()
    return raw if raw in _VALID else "v1"  # type: ignore[return-value]


def shadow_enabled() -> bool:
    return impl() in ("v2", "shadow")
