"""transcript_pointer_shadow — 【侧挂模块·默认关】C2 压缩后注入「原始历史文件」指针。

依据：计划 `docs/实施计划/46-cursor博客技术融合优化计划.md` §C2（⑬）。
对应方案稿：`docs/设计/cursor博客的技术融合到XEYO.md` §⑬（C2 压缩后注入「原始历史文件」指针，
治压缩后失忆）。

## 为什么（收益=治压缩失忆）
- C2 压后左段冻结 `working.c2_summary_text`，摘要缺细节时模型无法取回原始消息。
- 会话原始 JSONL 就在 `transcript_path(session_id)`（`~/.xeyo/sessions/{id}.jsonl`，append-only），
  `permissions/filesystem.py:206` 已放行读取。给模型一个**可 grep 的历史文件指针**，缺细节可找回。

## 侧挂契约（不改主逻辑）
- `enabled()`：读 `XEYO_C2_TRANSCRIPT_POINTER`（默认 0=关）。开=经 `install()` 挂在
  `prompt.pre_llm_inject.run_pre_llm_inject`；关=原逻辑（逐位不变）。
- **注入条件**：仅当该会话**已发生 C2 压缩**（`ctx.working.c2_summary_text` 非空）才注入，
  且**每会话只注入一次**（模块级 per-session 集合；重压缩不重复注入——指针字节稳定）。
- 注入块为 **inventory 类**（`# C2 后原始历史（background only）`），与现有装配契约兼容。
- **fail-open**：任何异常 → 交回原 `run_pre_llm_inject`，不破坏注入管线/预算。
"""

from __future__ import annotations

import importlib
import os

_TARGET_MODULE = "prompt.pre_llm_inject"
_HOOK_NAME = "run_pre_llm_inject"
_ENV = "XEYO_C2_TRANSCRIPT_POINTER"
_ORIG_NAME = "_ORIG__run_pre_llm_inject"
_INSTALLED_FLAG = "__c2_transcript_pointer_installed"
_TARGET = None

#: 注入块的标题头（须与 pre_llm_inject 的 inventory 归属头风格一致）。
_HEADER = "# C2 后原始历史（background only）"
#: 每会话注入一次（字节稳定）。
_SEEN_SESSIONS: set[str] = set()


def enabled() -> bool:
    """是否启用 C2 原始历史指针（升格后默认开；专用 env / 全局 promote 可关）。"""
    from sidecar.policy import side_enabled

    return side_enabled(_ENV)


def install() -> bool:
    """挂钩 `prompt.pre_llm_inject.run_pre_llm_inject`；返回是否实际安装（仅已启用才装）。"""
    if not enabled():
        return False
    global _TARGET
    mod = importlib.import_module(_TARGET_MODULE)
    if not getattr(mod, _INSTALLED_FLAG, False):
        if not hasattr(mod, _ORIG_NAME):
            setattr(mod, _ORIG_NAME, getattr(mod, _HOOK_NAME))
        setattr(mod, _HOOK_NAME, _run_pre_llm_inject_pointer)
        setattr(mod, _INSTALLED_FLAG, True)
    _TARGET = mod
    return True


def uninstall() -> None:
    global _TARGET
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    if getattr(mod, _INSTALLED_FLAG, False):
        setattr(mod, _HOOK_NAME, getattr(mod, _ORIG_NAME))
        setattr(mod, _INSTALLED_FLAG, False)
    _TARGET = None


def reset_seen() -> None:
    """清空 per-session 注入集合（供跨会话测试/重放）。"""
    _SEEN_SESSIONS.clear()


def _run_pre_llm_inject_pointer(projected, ctx):
    """包装 `run_pre_llm_inject`：在 C2 压缩后、且本会话未注入过时，加一条历史指针 inventory 块。"""
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    try:
        if not _should_inject(ctx):
            return getattr(mod, _ORIG_NAME)(projected, ctx)
        sid = (ctx.session_id or "").strip()
        block = transcript_pointer_block(sid)
        _SEEN_SESSIONS.add(sid)
        # 复用现有装配：把 inventory 块交给原函数前，先挂到 ctx 能感知的方式 —
        # 最稳做法是作为 inventory 块先行 prepend（fresh-user）或 append（after_tools）。
        # 为避免改动主函数装配，直接把块并入 injected 序列的产物上：
        out = getattr(mod, _ORIG_NAME)(projected, ctx)
        return _inject_pointer(out, block)
    except Exception:  # noqa: BLE001 — fail-open：指针注入失败不破坏管线
        return getattr(mod, _ORIG_NAME)(projected, ctx)


def _should_inject(ctx) -> bool:
    """是否注入：已启用 + 有 session_id + 已压缩 + 尚未对该会话注入过。"""
    if not enabled():
        return False
    if ctx is None:
        return False
    sid = (getattr(ctx, "session_id", None) or "").strip()
    if not sid or sid in _SEEN_SESSIONS:
        return False
    working = getattr(ctx, "working", None)
    # 已压缩 = c2_summary_text 非空（first compression 会把该字段冻结）。
    if working is None or not getattr(working, "c2_summary_text", ""):
        return False
    return True


def _inject_pointer(out, block: str):
    """把 pointer 块（inventory）插入最新用户消息之前的文本块序列。"""
    if not block:
        return out
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    try:
        # 复用 pre_llm_inject 的文本块插入 helper（若导出现则用；否则 append 到最后一个 user 消息）。
        if hasattr(mod, "prepend_text_blocks_to_last_user"):
            return mod.prepend_text_blocks_to_last_user(out, [block])
        # 兜底：append 到最后一个 user 消息文本前（对齐 inventory 前插语义）。
        return _prepend_to_last_user(out, block)
    except Exception:  # noqa: BLE001
        return out


def _prepend_to_last_user(out, block: str):
    """把 block 以文本块前缀插到最后一个 user 消息（若为文本）。"""
    for msg in reversed(out):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                msg["content"] = block + "\n" + content
                return out
            break
    return out


def transcript_pointer_block(session_id: str) -> str:
    """生成指向原始 JSONL 的 inventory 块；session_id 为空/无效返回空串。"""
    sid = (session_id or "").strip()
    if not sid:
        return ""
    try:
        from session.persistence import transcript_path

        path = transcript_path(sid)
    except Exception:  # noqa: BLE001 — 取路径失败则不注入指针（不猜测路径）
        return ""
    if not path:
        return ""
    return (
        f"{_HEADER}\n"
        f"\n"
        f"本会话完整原始消息记录（append-only JSONL）在：\n"
        f"`{path}`\n"
        f"压缩摘要缺细节时，可用 Read / Grep 打开该路径找回原始步骤。\n"
    )


def seen_sessions() -> set[str]:
    return set(_SEEN_SESSIONS)


def header() -> str:
    return _HEADER
