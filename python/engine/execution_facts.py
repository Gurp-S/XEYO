"""Opt-in facts derived from execution predicates, not parallel declarations."""
from __future__ import annotations
import os
from pathlib import Path

#: 事实合同总开关。**默认开**（2026-10-11 并入主链路）：A/B 实测它的**模型可见面增量 = 0**
#: （收执行两边逐字相同），增量全在引擎/审计面：``execution_metadata`` 的 ``exit_code`` /
#: ``complete``、Bash 的 ``status``，以及 env_facts 的**实时**可写面判定。
#: 注意 ``syntax`` 行**不跟着它**（另有 ``XEYO_ENV_FACTS_SYNTAX``，默认关，理由见 env_facts）。
#: 显式设 ``0`` 退回旧行为。
ENV = "XEYO_EXECUTION_FACT_CONTRACTS"
#: 工具结果的**截断事实**（原文在盘 / 原始规模 / 落盘路径）。**默认开**（2026-10-11 并入）：
#: A/B 实测 0/2 趟 → 2/2 趟；代价只在**真截断**时（完整结果不加字）。
#: 分页事实不走这里：由 ``grep_observation`` 承载（同一事实只留一处来源）。
#: 显式设 ``0`` 退回旧行为。
ENV_COMPLETENESS = "XEYO_TOOL_COMPLETENESS_FACTS"
#: 草稿目录写权限的**专属开关**（**默认开**，2026-10-11 并入）：``.xeyo/tmp/**`` 走受保护
#: 元数据的窄豁免（比既有 ``XEYO_ALLOW_PROTECTED_METADATA`` 的整棵放行窄得多，
#: 且 ``scratch_allowed`` 拒符号链接逃逸）。显式设 ``0`` 即收回该目录写权限。
#: 为什么单开一个：该豁免此前挂在 ``XEYO_EXECUTION_FACT_CONTRACTS``（事实合同开关）上
#: ⇒ "要不要上报事实"顺带决定了"能不能写盘"，两个关注点一个开关（口径错配）。
ENV_SCRATCH = "XEYO_SCRATCH_WRITABLE"


def enabled():
    return _default_on(ENV)


def _default_on(name: str) -> bool:
    """默认开的开关：未设置=开；显式 ``0``/``false``/``off``/``no`` 才关。"""
    from engine.flag_definitions import FLAGS, enabled as resolve
    if name in FLAGS:
        return resolve(name)
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "off", "no"}


def scratch_writable_enabled():
    return _default_on(ENV_SCRATCH)


def scratch_rel():
    """工作区内草稿目录的相对路径（唯一来源：权限豁免与事实上报共用）。"""
    from engine.harness_policy import enabled as rollout
    return ".xeyo/tmp" if rollout("XEYO_HARNESS_FACTS") else os.path.join(".xeyo", "tmp")


def scratch_path(cwd):
    """草稿目录绝对路径；cwd 为空返回 None（判不了就不给）。"""
    root = str(cwd or "").strip()
    if not root:
        return None
    return os.path.join(os.path.abspath(root), scratch_rel())


def completeness_facts_enabled():
    return _default_on(ENV_COMPLETENESS)


def truncation_fact(result):
    """截断事实：只在**真的截断**（有落盘原文）时返回 dict，否则 None。

    None 是常态：完整结果不占注意力（"能静默就不说话"）。
    两种来源同一形状——工具自带截断（bash truncate_for_model 写的 metadata.truncation）
    与 registry 输出预算 seam（metadata.spilled/spill_path/original_chars）。
    """
    meta = result.metadata or {}
    declared = meta.get("truncation")
    if isinstance(declared, dict) and declared.get("truncated"):
        return dict(declared)
    if not meta.get("spilled"):
        return None
    fact = {"truncated": True, "kind": str(meta.get("truncation") or "output_budget")}
    if meta.get("original_chars") is not None:
        fact["original_chars"] = meta["original_chars"]
    if meta.get("spill_path"):
        fact["spill_path"] = meta["spill_path"]
    return fact


def tool_receipt(result):
    receipt = result.execution_metadata() if enabled() else None
    # Acceptance travels with the actual result, not with the model's input.
    from memory.wsc_timing import enabled as timing_enabled
    request = (result.metadata or {}).get("compaction_request")
    if timing_enabled() and isinstance(request, dict) and not result.is_error and result.status == "ok":
        receipt = {**(receipt or result.execution_metadata()), "compaction_request": dict(request)}
    from synaptic.task_checkpoint import enabled as continuity_enabled
    for key in ("read_observation", "grep_observation"):
        observation = (result.metadata or {}).get(key)
        if continuity_enabled() and isinstance(observation, dict):
            receipt = {**(receipt or result.execution_metadata()), key: observation}
    if completeness_facts_enabled():
        truncation = truncation_fact(result)
        if truncation is not None:
            receipt = {**(receipt or result.execution_metadata()), "truncation": truncation}
    # 失败归因：**生产者决定有无**（bash 只在失败且开关开时才写），此处只负责送到出口。
    # 不另设开关——否则"算了"与"送到"两个开关会漂移（A/B 实测 def-2：事实写进了
    # metadata 却没进收执，模型端等于没修）。
    origin = (result.metadata or {}).get("error_origin")
    if isinstance(origin, str) and origin:
        receipt = {**(receipt or result.execution_metadata()), "error_origin": origin}
    return receipt


def scratch_allowed(path, cwd):
    if not (enabled() or scratch_writable_enabled()) or not cwd:
        return False
    root = Path(cwd).resolve()
    target = Path(path)
    target = (root / target if not target.is_absolute() else target).resolve()
    scratch = scratch_path(cwd) or ""
    if not scratch:
        return False
    try:
        relative = target.relative_to(scratch)
    except ValueError:
        return False
    # The reserved subtree itself cannot redirect outside the workspace.
    if Path(scratch).resolve() != Path(scratch):
        return False
    return not any(part.casefold() in {".git", ".xeyo", ".agents"} for part in relative.parts)


def writable(path, cwd):
    from permissions.filesystem import default_permission_context, check_write_permission_for_path, PermissionDecision
    from engine.write_store import WriteStore
    try:
        target = WriteStore(cwd)._canon(path)
        if check_write_permission_for_path(str(target), context=default_permission_context(cwd)) != PermissionDecision.ALLOW:
            return False
        parent = target
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        return parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
    except Exception:
        return False


def denial_text(decision, tool_input):
    message = f"Permission denied: {decision.reason}; rule={decision.matched_rule or 'unknown'}"
    if decision.reason == "bash_secret_read":
        from permissions.bash_secret_evidence import match as secret_match
        match = secret_match(str(tool_input.get("command") or ""))
        if match:
            # Category and location, never credentials or command contents.
            message += f"; evidence=credential_path; normalized_span={match.start()}:{match.end()}"
    elif decision.reason == "bash_write_target_unproven":
        message += "; evidence=write_target_not_resolved"
    return message
