"""Phase A 旁路 A/B 采集器：同一批真实调用跑两遍（开关关 / 开），按字段对照。

为什么单独一个脚本：三个旁路开关（``XEYO_GREP_PAGINATION_FACTS`` /
``XEYO_BASH_ERROR_ORIGIN`` / ``XEYO_TOOL_COMPLETENESS_FACTS``）默认关，效果必须能
**离线、零 API 成本、独立进程**地对照出来（运行中的后端仍加载旧模块，改完不等重启）。
执行口径与 ``scripts.tool_dryrun`` 完全一致：同一个 registry（同权限 gate / 审计 /
输出预算 seam），只是把结果按"开关关 vs 开"并排打印。

用法（在 ``python/`` 下）::

    py -3.11 -m scripts.ab_harness_facts                 # 关态
    $env:XEYO_GREP_PAGINATION_FACTS="1"; $env:XEYO_BASH_ERROR_ORIGIN="1"; `
    $env:XEYO_TOOL_COMPLETENESS_FACTS="1"; py -3.11 -m scripts.ab_harness_facts

判读：只认**差值**——关态输出必须与改动前逐字节相同（旁路红线），开态只增不减。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FLAGS = (
    "XEYO_GREP_PAGINATION_FACTS",
    "XEYO_BASH_ERROR_ORIGIN",
    "XEYO_TOOL_COMPLETENESS_FACTS",
    "XEYO_SCRATCH_WRITABLE",
    "XEYO_ENV_FACTS_EXTRA",
    "XEYO_TOOL_DESC_FACTS",
    "XEYO_GREP_SYMBOL_RANGES",
    "XEYO_EXECUTION_FACT_CONTRACTS",
    "XEYO_ENV_FACTS_SYNTAX",
    "XEYO_READ_STRUCTURE_HINT",
)


def _flag_states() -> str:
    return "  ".join(f"{name}={os.environ.get(name, '') or '-'}" for name in FLAGS)


async def _run(reg: Any, name: str, payload: dict[str, Any], index: int):
    from engine.abort import AbortController
    from msgtypes.message import ToolUse

    controller = AbortController(label=f"ab:{name}")
    return await reg.run(
        ToolUse(id=f"ab{index}", name=name, input=payload), controller, skip_ask=True
    )


def _facts(result: Any) -> dict[str, Any]:
    """收执事实：与 query_loop 投影用同一函数（不另立口径）。"""
    from engine.execution_facts import tool_receipt

    return dict(tool_receipt(result) or {})


def _receipt_header(facts: dict[str, Any], call_id: str) -> str:
    """把事实喂给真正的渲染器，打印模型会看到的那一行。"""
    from synaptic.receipt_render import render

    message = {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": call_id,
                "execution": facts,
                "content": "",
            }
        ],
    }
    block = render([message])[0]["content"][0]
    return str(block["content"]).splitlines()[0]


def _print_section(title: str) -> None:
    print("=" * 72)
    print(f"## {title}")
    print("=" * 72)


async def _main(args: argparse.Namespace) -> int:
    from scripts.tool_dryrun import _build_registry

    cwd = str(Path(args.cwd or ".").expanduser().resolve())
    reg, note = _build_registry(cwd, with_write_store=False)
    # 采样目标按 cwd 现算相对路径：脚本从 python/ 或仓库根跑都要能用。
    repo_root = Path(__file__).resolve().parents[2]
    gui_src = os.path.relpath(repo_root / "gui" / "src", cwd)
    grep_file = os.path.relpath(
        repo_root / "python" / "tools" / "grep_tool" / "grep_tool.py", cwd
    )

    print(f"cwd={cwd}")
    print(f"flags: {_flag_states()}")
    if note:
        print(f"[warn] {note}")
    index = 0

    # --- 1. Grep files_with_matches 分页：分母/下一页起点是否到得了模型 ---------
    _print_section("1. Grep files_with_matches（head_limit=3，命中远多于 3）")
    index += 1
    result = await _run(
        reg,
        "Grep",
        {
            "pattern": "queueDockView|queueCountLabel|xy-queue",
            "path": gui_src,
            "head_limit": 3,
        },
        index,
    )
    print(f"is_error={result.is_error} error_kind={result.error_kind}")
    print(f"metadata: {json.dumps(result.metadata or {}, ensure_ascii=False)}")
    print(f"header: {str(result.content or '').splitlines()[0]}")
    print(f"receipt: {_receipt_header(_facts(result), 'ab1')}")

    # --- 2. Grep matches 分页：next_offset ------------------------------------
    _print_section("2. Grep matches（head_limit=3，分页）")
    index += 1
    result = await _run(
        reg,
        "Grep",
        {
            "pattern": r"def \w+",
            "path": grep_file,
            "output_mode": "matches",
            "head_limit": 3,
        },
        index,
    )
    print(f"is_error={result.is_error} error_kind={result.error_kind}")
    print(f"metadata: {json.dumps(result.metadata or {}, ensure_ascii=False)}")
    print(f"tail: {str(result.content or '').splitlines()[-1]}")
    print(f"receipt: {_receipt_header(_facts(result), 'ab2')}")

    # --- 3. Bash：壳侧解析失败 → 谁写的这段文本 ------------------------------
    _print_section("3. Bash 解析错误归因（命令里 `&&` 后接赋值）")
    bad_command = 'cd "D:\\lea\\XenYon code" && $css = 1'
    index += 1
    result = await _run(reg, "Bash", {"command": bad_command}, index)
    print(f"is_error={result.is_error} error_kind={result.error_kind}")
    print(f"metadata: {json.dumps(result.metadata or {}, ensure_ascii=False)}")
    print("content（前 6 行）:")
    print("\n".join(str(result.content or "").splitlines()[:6]))
    print(f"receipt: {_receipt_header(_facts(result), 'ab3')}")

    # --- 4. Bash：首语句守卫（只判不跑，零副作用） ---------------------------
    _print_section("4. 前置守卫（prologue_applied：false = 放弃前置，不动用户命令语义）")
    from tools.bash_tool.runner import prologue_applied

    for sample in (
        'cd "D:\\lea\\XenYon code" && git status --porcelain',
        "param($x) Write-Output $x",
        "#requires -Version 7.0\nGet-Time",
        "using namespace System.Text",
        "[CmdletBinding()] param() Get-Time",
    ):
        print(f"  applied={prologue_applied(sample)!s:5}  {sample.splitlines()[0][:56]}")

    # --- 5. Bash：输出被截断 → 截断事实（原文在盘） ---------------------------
    _print_section("5. Bash 超长输出（截断事实 + 落盘路径）")
    index += 1
    result = await _run(reg, "Bash", {"command": '("x" * 80000)'}, index)
    meta = dict(result.metadata or {})
    print(f"is_error={result.is_error} error_kind={result.error_kind}")
    print(f"metadata: {json.dumps(meta, ensure_ascii=False, default=str)}")
    print(f"content_chars={len(str(result.content or ''))}")
    print(f"receipt: {_receipt_header(_facts(result), 'ab5')}")
    spill = meta.get("truncation", {}).get("spill_path") if isinstance(meta.get("truncation"), dict) else None
    if spill and os.path.isfile(str(spill)):
        os.remove(str(spill))
        print(f"[cleanup] 删除 A/B 产生的截断文件: {spill}")

    # --- 6. env_facts 常驻行：scratch / browser --------------------------------
    _print_section("6. env_facts 常驻行（scratch / browser 是否出现）")
    from engine.env_facts import render as render_env_facts

    print(render_env_facts(cwd))

    # --- 7. 草稿目录写权限：.xeyo/tmp 窄豁免 ---------------------------------
    _print_section("7. Write 到 .xeyo/tmp/ab-scratch.txt（窄豁免前后）")
    from scripts.tool_dryrun import _build_registry as _build_write_registry

    write_reg, _wn = _build_write_registry(cwd, with_write_store=True)
    scratch_target = os.path.join(".xeyo", "tmp", "ab-scratch.txt")
    index += 1
    result = await _run(write_reg, "Write", {"file_path": scratch_target, "content": "ab\n"}, index)
    print(f"is_error={result.is_error} error_kind={result.error_kind}")
    print(f"content: {str(result.content or '').strip()[:160]}")
    scratch_abs = Path(cwd) / scratch_target
    if scratch_abs.is_file():
        scratch_abs.unlink()
        print(f"[cleanup] 删除 A/B 写入的草稿文件: {scratch_abs}")

    # --- 8. Read 的 schema 描述（模型实际看到的那一行） ----------------------
    _print_section("8. Read description（apply_schema_budget 之后）")
    for schema in reg.schemas():
        if str(schema.get("name") or "") == "Read":
            print(str(schema.get("description") or ""))
            break

    # --- 9. Grep symbols：符号行号范围 --------------------------------------
    _print_section("9. Grep output_mode=symbols（位置是 start 还是 start-end）")
    index += 1
    result = await _run(
        reg,
        "Grep",
        {"pattern": "queueDockView", "path": gui_src, "output_mode": "symbols"},
        index,
    )
    print(f"is_error={result.is_error} error_kind={result.error_kind}")
    print("\n".join(str(result.content or "").splitlines()[:3]))

    # --- 10. 收执头：没有事实时是否还加头 -----------------------------------
    _print_section("10. 收执头（无事实的结果 / 有事实的结果）")
    from synaptic.receipt_render import render as render_receipt

    def _render(execution: dict[str, Any]) -> str:
        message = {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "abx",
                    "execution": execution,
                    "content": "body",
                }
            ],
        }
        block = render_receipt([message])[0]["content"][0]
        text = block["content"]
        return str(text).splitlines()[0] if isinstance(text, str) else text

    print(f"无事实: {_render({})}")
    print(f"有事实: {_render({'error_origin': 'requested_command'})}")

    # --- 11. 收益数据（带分母）：覆盖率 / 体量代价 --------------------------
    _print_section("11. 收益数据：事实覆盖率（分子/分母）与体量代价")
    taps = [
        os.path.relpath(repo_root / rel, cwd)
        for rel in ("gui/src", "python/tools", "python/engine", "python/synaptic")
    ]
    covered = 0
    truncated_hits = 0
    for tap in taps:
        index += 1
        res = await _run(
            reg, "Grep", {"pattern": "def |function |const ", "path": tap, "head_limit": 3}, index
        )
        observation = (res.metadata or {}).get("grep_observation") or {}
        was_paginated = bool(observation.get("next_offset"))
        truncated_hits += 1 if was_paginated else 0
        covered += 1 if ("total_records" in observation and observation.get("total_records")) else 0
    print(f"[Grep] 分页分母覆盖率: {covered}/{len(taps)} 趟 | 其中真分页: {truncated_hits}/{len(taps)}")

    trunc_facts = 0
    for size in (40000, 60000):
        index += 1
        res = await _run(reg, "Bash", {"command": f'("x" * {size})'}, index)
        meta = dict(res.metadata or {})
        if isinstance(meta.get("truncation"), dict) and meta["truncation"].get("truncated"):
            trunc_facts += 1
        spill = (meta.get("truncation") or {}).get("spill_path") if isinstance(meta.get("truncation"), dict) else None
        if spill and os.path.isfile(str(spill)):
            os.remove(str(spill))
    print(f"[Bash] 超长输出带截断事实: {trunc_facts}/2 趟")

    facts_line = render_env_facts(cwd)
    print(f"[env_facts] 事实条数={len(facts_line.split(' | '))} 字符={len(facts_line)}")
    print(f"[env_facts] 正文: {facts_line}")

    for schema in reg.schemas():
        if str(schema.get("name") or "") == "Read":
            print(f"[Read desc] 字符={len(str(schema.get('description') or ''))}")
            break

    index += 1
    res = await _run(
        reg,
        "Grep",
        {"pattern": "export function", "path": gui_src, "output_mode": "symbols", "head_limit": 5},
        index,
    )
    rows = [ln for ln in str(res.content or "").splitlines() if ":" in ln and not ln.startswith("Found")]
    spans = 0
    for row in rows:
        head = row.split(":")[1] if len(row.split(":")) > 1 else ""
        if "-" in head:
            spans += 1
    print(f"[symbols] 带行号范围的行: {spans}/{len(rows)} 行")

    header = _render({"call_id": "abx"})
    print(f"[收执头] 无事实结果的恒定开销: {len(header)} 字符/条（合同要求，未收敛）")

    # --- 12. XEYO_EXECUTION_FACT_CONTRACTS：模型可见面 / 引擎面 各自的增量 -----
    _print_section("12. execution_fact_contracts（EFC）：模型可见面 vs 引擎面")
    print(f"env_facts: {render_env_facts(cwd)}")
    index += 1
    ok = await _run(reg, "Bash", {"command": "echo ok"}, index)
    print(f"[成功] execution_metadata: {json.dumps(ok.execution_metadata(), ensure_ascii=False)}")
    print(f"[成功] receipt(模型可见): {_receipt_header(_facts(ok), 'ab12')}")
    index += 1
    bad = await _run(reg, "Bash", {"command": 'cd "D:\\lea\\XenYon code" && $x = 1'}, index)
    print(f"[失败] execution_metadata: {json.dumps(bad.execution_metadata(), ensure_ascii=False)}")
    print(f"[失败] receipt(模型可见): {_receipt_header(_facts(bad), 'ab13')}")

    # --- 13. Read：大文件窗口读的结构视图事实 + 结构视图能力证明 -------------
    _print_section("13. Read 大文件：窗口读事实（+ 结构视图本体）")
    big = os.path.relpath(
        repo_root / "gui" / "src" / "components" / "Composer.tsx", cwd
    )
    index += 1
    windowed = await _run(reg, "Read", {"file_path": big, "offset": 1875, "limit": 40}, index)
    wtext = str(windowed.content or "")
    print(f"[窗口读] is_error={windowed.is_error} chars={len(wtext)} "
          f"含结构视图事实={'structure view' in wtext}")
    if wtext.strip():
        print(f"[窗口读] 末行: {wtext.strip().splitlines()[-1][:160]}")
    index += 1
    outline = await _run(reg, "Read", {"file_path": big}, index)
    otext = str(outline.content or "")
    print(f"[无范围读] is_error={outline.is_error} chars={len(otext)} "
          f"metadata={json.dumps(outline.metadata or {}, ensure_ascii=False)[:200]}")
    print("[无范围读] 前 5 行:")
    print("\n".join(otext.splitlines()[:5]))

    # --- 14. browser 事实：有（常态）/ 缺失 两个分支 -------------------------
    _print_section("14. browser：常态一字不占 / 缺失时报警")
    from engine import env_facts as _ef

    print(f"[常态] {render_env_facts(cwd)}")
    saved = os.environ.get("LOCALAPPDATA")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LOCALAPPDATA"] = tmp
        _ef._FACTS_CACHE.clear()  # noqa: SLF001 — A/B 需要绕过进程内缓存
        print(f"[模拟缺失] {render_env_facts(cwd)}")
    if saved is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = saved
    _ef._FACTS_CACHE.clear()  # noqa: SLF001
    print(f"[恢复] {render_env_facts(cwd)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", default=".", help="registry 的 cwd（默认当前目录）")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
