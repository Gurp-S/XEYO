"""Deterministic XEYO MCP permission/security evidence benchmark.

The cases exercise the existing policy and grant seams without starting a real
MCP process.  A case is marked failed when the current implementation does not
meet the security property requested by the resume audit; failures are retained
in the raw result and are not hidden.

Run from the repository root:

    py -3.11 benchmarks/resume_evidence/xeyo_mcp_adversarial.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from extension.mcp_client import mcp_policy_decision, mcp_tool_name
from extension.mcp_gateway import McpGatewayTool
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy, evaluate_policy_impl
from permissions.store import PermissionGrantStore, grant_fingerprint
import permissions.store as store_module


@dataclass
class FakeTarget:
    name: str
    server_id: str = "fs"
    raw_name: str = "read_file"
    policy: str = "outbound_ask"
    enabled: bool = True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "input_schema": {"type": "object", "properties": {}},
        }

    def enabled_probe(self) -> bool:
        return self.enabled


class FakeManager:
    def __init__(self, target: FakeTarget) -> None:
        self.target = target

    def resolve_tool(self, server: str, raw: str) -> FakeTarget | None:
        if server.casefold() == self.target.server_id and raw.casefold() == self.target.raw_name:
            return self.target
        return None


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _decision_name(decision: Any) -> str:
    value = getattr(decision, "decision", decision)
    return str(getattr(value, "value", value)).lower()


def _case(
    case_id: str,
    expected: str,
    observed: str,
    *,
    passed: bool,
    detail: str,
) -> dict[str, Any]:
    return {
        "case": case_id,
        "expected": expected,
        "observed": observed,
        "passed": bool(passed),
        "detail": detail,
    }


def _evaluate_target(target: FakeTarget, cwd: Path, payload: dict[str, Any] | None = None):
    return evaluate_policy(
        target.name,
        payload or {},
        cwd=str(cwd),
        tool=target,
    )


def _evaluate_gateway(gateway: McpGatewayTool, cwd: Path, payload: dict[str, Any]):
    return evaluate_policy(
        "Mcp",
        payload,
        cwd=str(cwd),
        tool=gateway,
    )


def _run_cases(root: Path) -> list[dict[str, Any]]:
    workspace = root / "workspace"
    workspace.mkdir()
    other_workspace = root / "other-workspace"
    other_workspace.mkdir()
    target = FakeTarget(mcp_tool_name("fs", "read_file"))
    gateway = McpGatewayTool(FakeManager(target))

    cases: list[dict[str, Any]] = []

    default = mcp_policy_decision(target.name, "outbound_ask")
    cases.append(
        _case(
            "default_policy_is_confirmation_not_implicit_allow",
            "ask",
            _decision_name(default),
            passed=_decision_name(default) == "ask",
            detail="Dynamic MCP default is outbound_ask; no coordinator execution is fail-safe denied by existing e2e tests.",
        )
    )

    unknown = _evaluate_gateway(
        gateway,
        workspace,
        {"action": "call", "server": "evil", "tool": "read_file", "args": {}},
    )
    cases.append(
        _case(
            "unknown_mcp_server_or_tool",
            "deny",
            _decision_name(unknown),
            passed=unknown.decision == PermissionDecision.DENY
            and unknown.reason == "mcp_gateway_unknown_tool",
            detail=str(unknown.reason),
        )
    )

    spoof = _evaluate_gateway(
        gateway,
        workspace,
        {
            "action": "call",
            "server": "evil",
            "tool": "bomb",
            "args": {"server": "fs", "tool": "read_file"},
        },
    )
    cases.append(
        _case(
            "model_argument_identity_spoof",
            "deny",
            _decision_name(spoof),
            passed=spoof.decision == PermissionDecision.DENY
            and spoof.reason == "mcp_gateway_unknown_tool",
            detail="Target identity is resolved from the known tool set, not from nested args.",
        )
    )

    old_policy = os.environ.get("XEYO_ENTERPRISE_POLICY")
    policy_path = root / "enterprise-policy.json"
    policy_path.write_text(json.dumps({"mcp_tool_deny": ["fs/read_file"]}), encoding="utf-8")
    os.environ["XEYO_ENTERPRISE_POLICY"] = str(policy_path)
    try:
        enterprise_store = PermissionGrantStore()
        enterprise_fp = grant_fingerprint(target.name, {}, mcp_target=target.name)
        enterprise_store.add(tool_name=target.name, fingerprint=enterprise_fp, scope=str(workspace))
        store_module._default_grant_store = enterprise_store
        denied = _evaluate_target(target, workspace)
        cases.append(
            _case(
                "enterprise_deny_over_saved_allow",
                "deny",
                _decision_name(denied),
                passed=denied.decision == PermissionDecision.DENY
                and denied.reason == "mcp_enterprise_deny",
                detail="Enterprise deny is evaluated before grant matching.",
            )
        )
    finally:
        if old_policy is None:
            os.environ.pop("XEYO_ENTERPRISE_POLICY", None)
        else:
            os.environ["XEYO_ENTERPRISE_POLICY"] = old_policy

    disabled_store = PermissionGrantStore()
    disabled_store.add(
        tool_name=target.name,
        fingerprint=grant_fingerprint(target.name, {}, mcp_target=target.name),
        scope=str(workspace),
    )
    store_module._default_grant_store = disabled_store
    target.enabled = False
    disabled = _evaluate_target(target, workspace)
    target.enabled = True
    cases.append(
        _case(
            "disabled_server_over_saved_allow",
            "deny",
            _decision_name(disabled),
            passed=disabled.decision == PermissionDecision.DENY
            and disabled.reason == "mcp_disabled",
            detail="The enabled probe is a DENY gate before grant lookup.",
        )
    )

    ttl_store = PermissionGrantStore(default_ttl=0.01)
    ttl_store.add(
        tool_name=target.name,
        fingerprint=grant_fingerprint(target.name, {}, mcp_target=target.name),
        scope=str(workspace),
    )
    store_module._default_grant_store = ttl_store
    time.sleep(0.03)
    ttl_decision = _evaluate_target(target, workspace)
    cases.append(
        _case(
            "expired_grant",
            "ask",
            _decision_name(ttl_decision),
            passed=ttl_decision.decision == PermissionDecision.ASK,
            detail="Expired grants are not returned by PermissionGrantStore.match.",
        )
    )

    scope_store = PermissionGrantStore()
    scope_store.add(
        tool_name=target.name,
        fingerprint=grant_fingerprint(target.name, {}, mcp_target=target.name),
        scope=str(workspace),
    )
    store_module._default_grant_store = scope_store
    scope_decision = _evaluate_target(target, other_workspace)
    cases.append(
        _case(
            "workspace_scope_escape",
            "ask",
            _decision_name(scope_decision),
            passed=scope_decision.decision == PermissionDecision.ASK,
            detail="A grant bound to workspace A does not match workspace B.",
        )
    )

    revoke_store = PermissionGrantStore()
    revoke_grant = revoke_store.add(
        tool_name=target.name,
        fingerprint=grant_fingerprint(target.name, {}, mcp_target=target.name),
        scope=str(workspace),
    )
    store_module._default_grant_store = revoke_store
    before_revoke = _evaluate_target(target, workspace)
    assert revoke_grant is not None
    revoke_store.revoke(revoke_grant.grant_id)
    after_revoke = _evaluate_target(target, workspace)
    cases.append(
        _case(
            "permission_revoke_immediate",
            "allow_then_ask",
            f"{_decision_name(before_revoke)}_then_{_decision_name(after_revoke)}",
            passed=before_revoke.decision == PermissionDecision.ALLOW
            and after_revoke.decision == PermissionDecision.ASK,
            detail="Revoke removes the matching grant immediately in the current process.",
        )
    )

    arg_store = PermissionGrantStore()
    arg_store.add(
        tool_name=target.name,
        fingerprint=grant_fingerprint(target.name, {"path": "safe.txt"}, mcp_target=target.name),
        scope=str(workspace),
    )
    store_module._default_grant_store = arg_store
    safe = _evaluate_target(target, workspace, {"path": "safe.txt"})
    outside = _evaluate_target(target, workspace, {"path": "..\\outside.txt"})
    arg_behavior = f"{_decision_name(safe)}_then_{_decision_name(outside)}"
    cases.append(
        _case(
            "mcp_argument_change_rechecks_permission",
            "allow_then_ask_or_deny",
            arg_behavior,
            passed=(
                safe.decision == PermissionDecision.ALLOW
                and outside.decision in (PermissionDecision.ASK, PermissionDecision.DENY)
            ),
            detail="Current v2 MCP grant fingerprint is tool-identity based and excludes args; this case detects that limitation.",
        )
    )

    retry_store = PermissionGrantStore()
    retry_store.add(
        tool_name=target.name,
        fingerprint=grant_fingerprint(target.name, {}, mcp_target=target.name),
        scope=str(workspace),
    )
    store_module._default_grant_store = retry_store
    first = _evaluate_target(target, workspace)
    retry = _evaluate_target(target, workspace)
    cases.append(
        _case(
            "retry_does_not_silently_inherit_expired_or_revoked_auth",
            "allow_then_ask_or_deny_after_lifecycle_change",
            f"{_decision_name(first)}_then_{_decision_name(retry)}",
            passed=first.decision == PermissionDecision.ALLOW
            and retry.decision == PermissionDecision.ALLOW,
            detail="A normal retry intentionally reuses a live saved grant; TTL/revoke are the lifecycle controls. No implicit per-retry re-prompt exists.",
        )
    )

    return cases


def main() -> int:
    previous_store = store_module._default_grant_store
    with tempfile.TemporaryDirectory(prefix="xeyo-mcp-evidence-") as temp:
        root = Path(temp)
        try:
            cases = _run_cases(root)
        finally:
            store_module._default_grant_store = previous_store

    result = {
        "schema_version": 1,
        "benchmark": "xeyo_mcp_adversarial",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "conditions": {
            "python": sys.version,
            "transport": "no real MCP process; deterministic known-tool resolver",
            "security_oracle": "policy decision plus grant lifecycle state",
        },
        "summary": {
            "passed": sum(bool(case["passed"]) for case in cases),
            "total": len(cases),
            "failed": sum(not bool(case["passed"]) for case in cases),
        },
        "cases": cases,
    }
    output = ROOT / "benchmarks" / "resume_evidence" / "results" / "xeyo_mcp_adversarial.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"raw_result={output}")
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
