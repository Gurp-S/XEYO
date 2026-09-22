# -*- coding: utf-8 -*-
"""F2 · 引擎档案 dump —— 评测发车前把「实际生效的那一档」钉成一份可比对的 JSON。

动机（2026-09-21 实测）：记忆开关存在两条互不兼容的读路径 ——
`os.environ` 读的（WSC）尊重工作区 settings，`memory_switches.get_value()` 读的
（L5 / TOOL_AGING / MEMORY_INDEX_LIVE）**只读 home 级**，因为它们不透传 cwd。
后果：工作区写了 `XEYO_L5: v61`，运行时 `l5_mode()` 仍返回 `project`。
所以**不看档案就无法知道一轮评测到底跑在哪个档上**，消融差值也无从复现。

用法：
    cd python && py -3.11 scripts/dump_engine_profile.py [--cwd <工作区>] [-o out.json]

只读，不写任何引擎状态。
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001 — 档案不得因取不到某项而整体失败
        return f"<unavailable: {type(exc).__name__}>"


def _baseline_sha() -> str:
    """HEAD 或 index 的 SHA；用 `git stash create` 会写入对象库，故不采用。"""
    return _git("rev-parse", "HEAD")


def _worktree_dirty() -> dict:
    raw = _git("status", "--porcelain")
    if raw.startswith("<"):
        return {"error": raw}
    lines = [l for l in raw.splitlines() if l.strip()]
    modified = [l for l in lines if l[:2] not in ("??",)]
    untracked = [l for l in lines if l[:2].strip() == "??"]
    return {
        "modified_tracked": len(modified),
        "untracked": len(untracked),
        "clean": not lines,
        # 前 40 条足以指认脏在哪；全量太长且不随时间稳定。
        "sample": [l for l in lines[:40]],
    }


def _memory_switch_profile(cwd: str) -> dict:
    """逐开关并列 home 档与工作区档。

    ⚠️ 不能只比这两个值：若工作区值恰好等于注册表默认，两档会**偶然相等**，
    看起来"cwd 被尊重"其实没有。所以另附 `getter_accepts_cwd`（结构判据）。
    """
    import inspect

    from memory import l5_flag
    from memory.memory_switches import MEMORY_SWITCHES, get_value

    # 运行时 getter 是否接受 cwd —— 结构性判据，不受取值偶然相等影响。
    cwd_blind_getters = []
    for fn in (l5_flag.l5_mode, l5_flag.use_v61):
        try:
            if "cwd" not in inspect.signature(fn).parameters:
                cwd_blind_getters.append(fn.__qualname__)
        except (TypeError, ValueError):
            cwd_blind_getters.append(f"{fn.__qualname__}<unintrospectable>")
    try:
        from engine.aging import aging_enabled

        if "cwd" not in inspect.signature(aging_enabled).parameters:
            cwd_blind_getters.append("aging_enabled")
    except Exception:  # noqa: BLE001
        pass

    out: dict[str, dict] = {}
    for key, _label, _allowed, default, _exposed, _runtime, _auth in MEMORY_SWITCHES:
        home_val = get_value(key, None)
        ws_val = get_value(key, cwd)
        out[key] = {
            "registry_default": default,
            "effective_home_only": home_val,
            "if_cwd_respected": ws_val,
            "values_differ": home_val != ws_val,
        }
    return {"switches": out, "cwd_blind_runtime_getters": cwd_blind_getters}


def _live_getters() -> dict:
    """运行时**真正**会读到的值（这些是可能忽略 cwd 的那一层）。"""
    from engine.aging import aging_enabled
    from memory.l5_flag import l5_mode, use_v61

    return {
        "l5_mode": l5_mode(),
        "use_v61": use_v61(),
        "aging_enabled": aging_enabled(),
        "wsc_from_environ": os.environ.get("XEYO_WSC", ""),
    }


def _t_now_registry() -> dict:
    from prompt.pre_llm_inject import T_NOW_BLOCK_HARD_CAP, T_NOW_BLOCK_REGISTRY

    pipes: dict[str, int] = {}
    for name, spec in T_NOW_BLOCK_REGISTRY.items():
        pipe = str(spec.get("pipe", "?"))
        pipes[pipe] = pipes.get(pipe, 0) + 1
    return {
        "count": len(T_NOW_BLOCK_REGISTRY),
        "hard_cap": T_NOW_BLOCK_HARD_CAP,
        "by_pipe": pipes,
        "names": sorted(T_NOW_BLOCK_REGISTRY),
        "dedup_declared": sorted(
            n for n, s in T_NOW_BLOCK_REGISTRY.items() if s.get("dedup")
        ),
        "event_no_dedup_no_quota": sorted(
            n for n, s in T_NOW_BLOCK_REGISTRY.items()
            if str(s.get("pipe", "")).upper().find("EVENT") >= 0
        ),
    }


def _context_windows() -> dict:
    from engine.query_engine import CONSERVATIVE_CONTEXT_WINDOW, KNOWN_CONTEXT_WINDOWS

    return {
        "conservative_fallback": CONSERVATIVE_CONTEXT_WINDOW,
        "known": [{"model": m, "window": w} for m, w in KNOWN_CONTEXT_WINDOWS],
    }


def _bash_policy(cwd: str) -> dict:
    from permissions.workspace_policy import load_workspace_policy

    p = load_workspace_policy(cwd)
    return {
        "policy_file_exists": bool(getattr(p, "exists", False)),
        "source_path": getattr(p, "source_path", None),
        "bash": getattr(p, "bash", None),
        "bash_routing": getattr(p, "bash_routing", None),
        "bash_escalate": getattr(p, "bash_escalate", None),
        "remote_bash": getattr(p, "remote_bash", None),
        "parse_error": getattr(p, "parse_error", None),
    }


def _extension_settings(cwd: str) -> dict:
    """直读两份 settings.json —— 绕开各模块自己的解析差异，取原始事实。"""
    out: dict[str, dict] = {}
    for label, path in (
        ("home", Path.home() / ".xeyo" / "settings.json"),
        ("workspace", Path(cwd) / ".xeyo" / "settings.json"),
    ):
        entry: dict = {"path": str(path), "exists": path.exists()}
        if path.exists():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                entry["memory"] = d.get("memory", {})
                entry["enabled_extensions"] = d.get("enabled_extensions", "(absent)")
                entry["top_keys"] = sorted(d.keys())
            except Exception as exc:  # noqa: BLE001
                entry["parse_error"] = repr(exc)
        out[label] = entry
    return out


def build_profile(cwd: str) -> dict:
    profile = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "repo_root": str(REPO_ROOT),
        "eval_cwd": str(Path(cwd).resolve()),
        "baseline": {"head_sha": _baseline_sha(), "branch": _git("rev-parse", "--abbrev-ref", "HEAD")},
        "worktree": _worktree_dirty(),
        "memory_switches": _memory_switch_profile(cwd),
        "live_getters": _live_getters(),
        "t_now_registry": _t_now_registry(),
        "context_windows": _context_windows(),
        "bash_policy": _bash_policy(cwd),
        "extension_settings": _extension_settings(cwd),
    }
    # 档案自证：把「运行时 getter 是否结构性地看不见 cwd」提成一句人话。
    profile["cwd_settings_unreachable_via"] = profile["memory_switches"][
        "cwd_blind_runtime_getters"
    ]
    profile["memory_switches"] = profile["memory_switches"]["switches"]
    return profile


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cwd", default=str(REPO_ROOT), help="被评测的工作区（默认仓库根）")
    ap.add_argument("-o", "--out", default="", help="输出 JSON 路径；缺省打印到 stdout")
    args = ap.parse_args()

    with contextlib.suppress(Exception):
        # 桥接 settings→env，让 env 读法（WSC）拿到与生产一致的生效值。
        from memory.memory_switches import apply_to_environ

        apply_to_environ(args.cwd)

    profile = build_profile(args.cwd)
    text = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"written: {args.out}")
        print(f"cwd_settings_unreachable_via: {profile['cwd_settings_unreachable_via']}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
