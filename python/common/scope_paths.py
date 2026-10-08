"""写范围（scope）路径归一：一个实现，两档政策（由调用方显式声明）。

同一段"scope 路径怎么归一、怎么比"的逻辑原先在两处各自实现：
``engine/scheduler._norm_scope_path``（同会话 DAG 调度）与
``coord/store.norm_scope_path``（跨进程派发层）。两处**有意不同**：

- :data:`POLICY_SESSION`：纯字符串归一（反斜杠→/、小写、剥 ``./`` 与工作区根
  前缀），不做真实路径解析。同会话内两个 scope 来自同一模型、同一轮对话，
  精确交集够用，且不碰磁盘。
- :data:`POLICY_DISPATCH`：真实解析（``expanduser`` + ``resolve`` + ``relative_to``）、
  **不折叠大小写**。跨进程派发层取严：``src/`` 与 ``src/a.py`` 会在合并层真撞车，
  精确字符串交集漏检 ⇒ 双放行 ⇒ 冲突重试烧 token。

分歧是设计，不是重复。本模块收的是**实现**：反斜杠归一、空值、``./`` 这些共用
语义此前有两份拷贝（改一处漏一处）；政策仍由调用方点名，行为逐字节不变。

未裁定项（不随本次收口一起动）：大小写是否该折叠。Windows 上派发档不折叠会漏检
``Src/a.py`` 与 ``src/a.py`` 指向同一文件；改它等于改冲突判定，需要单独决策。
"""

from __future__ import annotations

from pathlib import Path

#: 同会话调度档：字符串归一 + 折叠大小写，不解析真实路径。
POLICY_SESSION = "session"
#: 跨进程派发档：真实解析 + 相对化，不折叠大小写（取严）。
POLICY_DISPATCH = "dispatch"

_POLICIES = frozenset({POLICY_SESSION, POLICY_DISPATCH})


def norm_scope_path(value: str, root: str | Path | None = None, *, policy: str) -> str:
    """按 ``policy`` 归一一个 scope 路径；空输入 → ``""``。"""
    if policy == POLICY_SESSION:
        return _session_norm(value, root)
    if policy == POLICY_DISPATCH:
        return _dispatch_norm(value, root)
    raise ValueError(f"unknown scope path policy: {policy!r}")


def _session_norm(path: str, root: str | Path | None) -> str:
    """同会话档：反斜杠→/、小写、剥 ``./`` 与绝对根前缀（纯字符串）。"""
    p = (path or "").replace("\\", "/").strip().lower()
    if not p:
        return ""
    while p.startswith("./"):
        p = p[2:]
    if root is not None:
        root_s = (
            str(Path(root).expanduser().resolve()).replace("\\", "/").strip().lower()
        )
        if root_s and (p == root_s or p.startswith(root_s + "/")):
            p = p[len(root_s):].lstrip("/")
    return p


def _dispatch_norm(path: str, root: str | Path | None) -> str:
    """派发档：真实解析 + 相对化；无法归一 → 原样剥 ``./`` 的 posix 形式。"""
    raw = (path or "").strip().replace("\\", "/")
    if not raw:
        return ""
    try:
        p = Path(raw).expanduser()
        if p.is_absolute() and root is not None:
            return p.resolve().relative_to(Path(root).resolve()).as_posix()
        if p.is_absolute():
            return p.resolve().as_posix()
        return p.as_posix()
    except (OSError, ValueError):
        return raw.lstrip("./")


__all__ = ["POLICY_DISPATCH", "POLICY_SESSION", "norm_scope_path"]
