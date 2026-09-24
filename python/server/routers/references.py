"""References 域路由：``GET /v1/references/files`` 返回工作区文件候选（供 GUI 的
``@`` 引用弹层）。

与 ``/v1/slash`` / ``/v1/skills`` 同源安全模型：``require_loopback``（仅本机客户端）。
纯只读目录扫描，不改任何状态；不进模型上下文——插入的 ``@相对路径`` 由 Agent
用既有文件工具按需读取（按需引用，不预载全量）。

过滤规则：``q`` 对相对路径做大小写不敏感子串匹配；跳过重目录
（node_modules/.git/__pycache__/target/dist 等）；按「路径深度 → 字典序」排序，
返回前 ``limit`` 条。``q`` 为空时返回工作区顶层文件/目录，供 ``@`` 刚键入时浏览。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Header, Query, Request

from server.deps import api_error
from server.local_gate import require_loopback

router = APIRouter(tags=["references"])


def _checked_workspace(value: str) -> str:
    """工作区根目录**允许**是任意绝对路径（桌面 app 的 space 由用户自己选，
    与 ``POST /v1/workspace`` 同一口径），本函数不裁决位置。

    要裁决的是两类「看起来合法、但落点不是客户端要的那个」的写法：
    - 空 / 纯空白：``os.path.realpath(" ")`` 归一成**服务端进程当前目录**，
      于是「列 A 空间」静默变成「列 CWD」——这是静默清洗，必须 422；
    - 含控制字符：``os.path.isdir`` 一类会以「目录不存在」的形式把它吞掉。
    """
    text = "" if value is None else str(value)
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        raise api_error(422, "workspace 含控制字符", "invalid_request")
    if not text.strip():
        raise api_error(422, "workspace 不能为空", "invalid_request")
    return text.strip()

# 命中即整棵剪枝的重目录名（不进递归）。
SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "target",
        "dist",
        "build",
        ".workbuddy",
        ".idea",
        ".vscode",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        ".next",
        ".turbo",
    }
)
MAX_SCAN = 4000  # 扫描条目硬顶，防超大工作区拖垮请求
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def _iter_candidates(root: str):
    """迭代 root 下（跳过重目录）的相对路径。目录带 ``/`` 后缀参与匹配但不计入结果。"""
    stack = [""]
    seen = 0
    while stack:
        rel = stack.pop()
        abs_dir = os.path.join(root, rel) if rel else root
        try:
            entries = list(os.scandir(abs_dir))
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if seen > MAX_SCAN:
                return
            entry_rel = f"{rel}/{entry.name}" if rel else entry.name
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in SKIP_DIRS:
                    stack.append(entry_rel)
                continue
            yield entry_rel.replace("\\", "/")


@router.get("/v1/references/files")
def list_file_references(
    request: Request,
    workspace: str = Query(min_length=1, max_length=1024),
    q: str = Query(default="", max_length=256),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    """返回工作区内匹配 ``q`` 的文件相对路径（``/`` 分隔），供 @ 引用弹层。"""
    _ = authorization  # 门禁放行本机；保留 Bearer 语义位，与 /v1/skills 一致。
    require_loopback(request)
    root_arg = _checked_workspace(workspace)

    root = os.path.realpath(root_arg)
    if not os.path.isdir(root):
        return {"ok": False, "files": [], "message": "workspace 不存在"}

    needle = q.strip().lower()
    matches = [rel for rel in _iter_candidates(root) if needle in rel.lower()]
    matches.sort(key=lambda p: (p.count("/"), p.lower()))
    return {"ok": True, "files": matches[:limit]}
