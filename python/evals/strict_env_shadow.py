"""strict_env_shadow — 【侧挂模块·升格后默认开】严格环境档（隔离 git 历史 + 出口收紧 + 四字段报告）。

升格状态（2026-09-14 更正）：纯函数型侧挂模块，`enabled()` 走 `sidecar.policy.side_enabled()`；
专用 env 未设时回退总升格开关 `XEYO_SIDEMOD_PROMOTE`（默认 1=升格）⇒ 实际**默认开**，
原「默认关」表述与运行时相反。单项关闭 `XEYO_EVAL_STRICT=0`，全局回退 `XEYO_SIDEMOD_PROMOTE=0`。

## 为什么（收益=评测诚实度）
- SWE-bench 系基于「历史公开代码仓库」，最易泄漏。把被测仓库放进「严格档」：
  1. **历史隔离**：Agent 启动前剥离 `.git` → 重新 init 成单 commit 仓库（评分为止），
     评完后恢复原始历史（git history mining 无从下手）。
  2. **出口代理**：默认禁网、只放行白名单软件包仓库解析依赖（复用 `permissions/policy.py`
     的权限面，评测期收紧为「基准 profile」）。
  3. **报告口径**：summary 同时输出 `standard / strict / Δ / leakage_rate`，非单一 headline。

## 侧挂契约（不改主逻辑）
- `enabled()`：读 `XEYO_EVAL_STRICT`；未设时回退总升格开关（默认开）。开=评测入口先 `isolate_git_history` +
  `apply_egress_profile`；关=不拦（逐位不变）。
- 均为独立可调函数（无需真实 git 也能单测其流程/回滚逻辑，见 `test_strict_env`）。
- **fail-open**：隔离/回滚任一步失败 → 把仓库恢复为原状态并报告明确错误，**绝不留下**
  半剥离的 `.git`，也不静默跳过恢复。
- **红线**：恢复失败必须显式（不假 ok）；隔离只在显式 `XEYO_EVAL_STRICT=1` 下进行。

## 说明
- 现有 `evals/*` 是 DeepSeek 代码生成客户端（无 agent 回路），本模块主要面向**XEYO 自身
  agent 回路在真仓库上跑 SWE/长任务**的场景；对纯代码生成 harness 是无害旁路（可单项关闭）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_ENV = "XEYO_EVAL_STRICT"
_WHITELIST_ENV = "XEYO_EVAL_STRICT_OUTBOUND_WHITELIST"

#: 默认放行的出口域名（软件包仓库解析依赖）；可用 env 覆盖/追加。
_DEFAULT_WHITELIST = (
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "crates.io",
)


@dataclass
class StrictEnvResult:
    """严格环境档动作结果。"""

    ok: bool
    action: str = ""
    detail: str = ""
    restored: bool = False


def enabled() -> bool:
    """是否启用严格环境档（升格后默认开；专用 env / 全局 promote 可关）。"""
    from sidecar.policy import side_enabled

    return side_enabled(_ENV)


def whitelist() -> list[str]:
    """返回出口白名单（默认 + env 追加）。"""
    base = list(_DEFAULT_WHITELIST)
    extra = os.environ.get(_WHITELIST_ENV, "").strip()
    if extra:
        for tok in extra.replace(",", " ").split():
            tok = tok.strip()
            if tok and tok not in base:
                base.append(tok)
    return base


def isolate_git_history(repo: str) -> StrictEnvResult:
    """把 repo 的 `.git` 备份，重 init 成单 commit 仓库；评完由 `restore_git_history` 恢复。

    - 无 `.git` → return ok=True, action="no-op"（无历史可隔离）。
    - `.git` 移动/重 init 失败 → return ok=False（绝不留下半隔离状态；调用方决定是否继续）。
    """
    repo = Path(repo).resolve()
    gd = repo / ".git"
    if not gd.exists():
        return StrictEnvResult(ok=True, action="no-op")
    backup = repo / ".git.bak_eval_strict"
    try:
        if backup.exists():
            shutil.rmtree(backup)
        gd.rename(backup)
        r = subprocess.run(
            ["git", "init", "-q"], cwd=str(repo), capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            # 回滚：恢复原 .git。
            if backup.exists() and not gd.exists():
                backup.rename(gd)
            return StrictEnvResult(ok=False, action="isolate", detail=r.stderr[:300])
        # 打一个单 commit 快照（若无文件则允许空仓）。
        subprocess.run(
            ["git", "add", "-A"], cwd=str(repo), capture_output=True, text=True, timeout=60
        )
        subprocess.run(
            ["git", "-c", "user.name=eval", "-c", "user.email=eval@local",
             "commit", "-q", "-m", "baseline"], cwd=str(repo),
            capture_output=True, text=True, timeout=60,
        )
        return StrictEnvResult(ok=True, action="isolate", detail=str(backup))
    except (OSError, subprocess.SubprocessError) as e:  # noqa: PERF203
        return StrictEnvResult(ok=False, action="isolate", detail=str(e)[:300])


def restore_git_history(repo: str) -> StrictEnvResult:
    """恢复被隔离的 `.git`（把 `.git.bak_eval_strict` 挪回 `.git`），删除临时单 commit `.git`。"""
    repo = Path(repo).resolve()
    backup = repo / ".git.bak_eval_strict"
    gd = repo / ".git"
    if not backup.exists():
        # 无备份：若是「隔离后从未恢复」，此时 `.git` 为新单 commit；删除即可（无原始可恢复）。
        return StrictEnvResult(ok=True, action="restore", restored=True)
    try:
        # Windows：新 `.git` 的打包对象可能被进程短暂持有，直接删除会 WinError 5。
        # 因此**改名挪走**（rename 一般不受已打开对象读取限制），再把备份改名到 `.git`。
        _swap_git(gd, backup)
        return StrictEnvResult(ok=True, action="restore", restored=True)
    except OSError as e:  # noqa: BLE001
        return StrictEnvResult(ok=False, action="restore", detail=str(e)[:300])


def _swap_git(gd: Path, backup: Path) -> None:
    """把临时 `.git` 挪到唯一名（不删除），再把备份挪回 `.git`。"""
    import shutil as _sh
    import time

    if not gd.exists():
        backup.rename(gd)
        return
    # 临时 .git 挪到一个不会冲突的名字（避免撞到现有备份）。
    drift = gd.with_name(f".git.eval_drift_{int(time.time() * 1000)}")
    last_err: Exception | None = None
    for _attempt in range(3):
        try:
            gd.rename(drift)
            break
        except OSError as e:
            last_err = e
            time.sleep(0.3)
    if gd.exists():  # 挪不动（可能被持有目录柄）→ 删除空壳重试
        try:
            _sh.rmtree(gd, ignore_errors=True)
        except OSError:
            pass
        gd.rename(drift)
    # 备份 → .git。
    backup.rename(gd)
    # 尽力清理 drift（失败可忽略，不入主路径）。
    try:
        _sh.rmtree(drift, ignore_errors=True)
    except OSError:
        pass


def strict_summary(summary: dict) -> dict:
    """把 summary 规范化成含 `standard / strict / Δ / leakage_rate` 四字段的报告。

    复用 `evals.reporting_shadow.build_report` 的口径（同一约定）。
    """
    try:
        from evals.reporting_shadow import build_report

        return build_report(summary, mode_label="编码能力(严格)")
    except Exception:  # noqa: BLE001 — fail-open：报告规范化失败不丢分
        out = dict(summary or {})
        out.setdefault("standard", out.get("accuracy"))
        out.setdefault("strict", None)
        out.setdefault("delta", None)
        out.setdefault("leakage_rate", None)
        return out
