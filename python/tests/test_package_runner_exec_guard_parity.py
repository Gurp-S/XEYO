"""包运行器的内置工具表守卫必须覆盖全部同形入口（npx / dlx / exec）。

`_classify_tool_runner` 的 docstring 写明它的存在理由：「目标程序必须在已知工具表内
（不认任意包名）」——因为 `npx <pkg>` 跑的是**远端包里的 bin**，命令里看不见可审计
来源（模块 docstring 第 2 轴）。2026-10-04 实测这张表只接在 `npx`/`bunx`/
`pnpm|yarn dlx` 上，`npm exec` / `pnpm exec` / `yarn exec`（同一语义）整词命中
`_SUB_DEV` ⇒ 任意包名自动放行，端到端 `evaluate_policy("Bash", {"command":
"pnpm exec evil"})` = ALLOW（matched_rule=bash_dev_tool_allow）。

同族里 `npm run <script>` **不在**本守卫范围，且不许被收进来：它跑工作区
package.json 里可读的脚本，是 docstring 明确承认的 dev 信任档。两头都钉：
放行的继续放行，不该放行的继续不放行。

现网分母（`~/.xeyo/sessions` 421 个转录、10,781 条 Bash 命令）：
`npm|pnpm|yarn|bun exec` = 0 次，`npx` = 101 次 ⇒ 收口不改变任何既有工作流。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from permissions.bash_readonly import DEV, READONLY, analyze, verdict_kind  # noqa: E402
from permissions.policy import evaluate_policy  # noqa: E402

UNKNOWN = "definitely-not-a-known-tool-xyz"
KNOWN = "eslint"

#: 语义等同的入口：目标 = 远端包的 bin，必须过 _KNOWN_TOOLS。
RUNNER_FORMS = (
	"npx {t}",
	"pnpm dlx {t}",
	"yarn dlx {t}",
	"npm exec {t}",
	"pnpm exec {t}",
	"yarn exec {t}",
)

#: 把目标藏在选项 / 动作词之后也不能绕。
SNEAK_FORMS = (
	"npx --yes {t}",
	"npm exec --yes {t}",
	"npm --yes exec {t}",
	"pnpm exec -- {t}",
	"yarn dlx -p {t}",
	"npx -y {t} --help",
)


def _admitted(kind: str) -> bool:
    return kind in (READONLY, DEV)


def test_control_known_tool_still_admitted_through_every_runner() -> None:
    """正向自证：表内目标在每个入口照旧放行。

    缺了这条，"unknown 被挡住"可能只是因为整个入口被关掉了。
    """
    kinds = {form.format(t=KNOWN): verdict_kind(form.format(t=KNOWN)) for form in RUNNER_FORMS}
    assert all(_admitted(k) for k in kinds.values()), kinds


@pytest.mark.parametrize("form", RUNNER_FORMS)
def test_unknown_package_never_auto_allowed(form: str) -> None:
    verdict = analyze(form.format(t=UNKNOWN))
    assert verdict.kind == "", verdict
    assert verdict_kind(form.format(t=UNKNOWN)) == "", form


@pytest.mark.parametrize("form", SNEAK_FORMS)
def test_runner_rejects_target_hidden_behind_options(form: str) -> None:
    assert verdict_kind(form.format(t=UNKNOWN)) == "", form


def test_runner_parity_same_target_same_kind() -> None:
    """结构不变量：同目标跨入口必须同类 ⇒ 以后新增入口漏接守卫会当场红。"""
    unknown_kinds = {form: verdict_kind(form.format(t=UNKNOWN)) for form in RUNNER_FORMS}
    assert set(unknown_kinds.values()) == {""}, unknown_kinds
    known_kinds = {form: verdict_kind(form.format(t=KNOWN)) for form in RUNNER_FORMS}
    assert all(_admitted(k) for k in known_kinds.values()), known_kinds


def test_npm_run_workspace_script_is_outside_the_guard() -> None:
    """反向自证：`npm run` 跑工作区脚本，属 dev 信任档，守卫不许吃它。"""
    assert verdict_kind("npm run build") == DEV
    assert verdict_kind("npm test") == DEV


def test_end_to_end_policy_asks_for_unknown_package() -> None:
    """判据落在被量对象上：真实策略层决定，而不是只看分类器。"""
    cwd = tempfile.mkdtemp(prefix="xeyo_exec_guard_")
    rows = []
    for form in RUNNER_FORMS:
        cmd = form.format(t=UNKNOWN)
        decision = evaluate_policy("Bash", {"command": cmd}, cwd=cwd)
        rows.append((cmd, str(decision.decision), getattr(decision, "matched_rule", "")))
    assert all(d[1].endswith("ASK") for d in rows), rows
