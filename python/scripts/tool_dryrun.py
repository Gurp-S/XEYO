"""工具面 dry-run：独立进程里用**当前代码**跑真实工具，打印判定字段。

动机（与 ``scripts.t_now_dryrun`` 同一摩擦）：改工具面（Read 结构视图、写守卫归因、
Glob 规模事实……）之后，运行中的后端仍加载旧模块——模型只能等重启才看得到效果。
这个脚本把"改-验"闭环从进程生命周期里解耦：给定调用序列，直接建 registry 并按
``registry.run`` 跑（同一权限 gate / 审计 / 输出预算 seam），打印 content /
is_error / status / error_kind / retryable / metadata 全文 + 判定字段高亮
（``structured`` / ``view`` / ``missing_read`` / ``reason`` …）。

用法（离线、零 API 成本）::

    py -3.11 -m scripts.tool_dryrun --list
    py -3.11 -m scripts.tool_dryrun --describe Read
    py -3.11 -m scripts.tool_dryrun --tool Read --args '{"file_path":"python/engine/query_loop.py"}'
    py -3.11 -m scripts.tool_dryrun --call '{"name":"Read","input":{"file_path":"a.py"}}' \
        --call '{"name":"Edit","input":{"file_path":"a.py","old_string":"x","new_string":"y"}}'

多把 ``--call`` 共享同一个 registry 与同一份 read-state（顺序即调用顺序）——写守卫
（``missing_read`` / baseline dropped）这类**跨调用**判定只有按序跑才复现得出来。

注意：这是**真跑**，Write/Edit 会真写盘（请在临时副本上跑）；``--dry`` 只打调用面。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: 元数据里"决定下一位读者怎么反应"的字段：先摆出来，其余按原样跟在后头。
_HIGHLIGHT = (
    "structured",
    "view",
    "missing_read",
    "reason",
    "baseline_epoch",
    "baseline_dropped",
    "permission_action",
    "permission_reason",
    "permission_reason_code",
    "truncated",
    "total_lines",
    "returned_lines",
    "bytes",
    "size_bytes",
    "error_kind",
    "side_effect",
    "execution_complete",
    "exit_code",
)


def _parse_call(raw: str) -> dict[str, Any]:
    try:
        row = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"--call 不是合法 JSON: {exc}")
    if not isinstance(row, dict):
        raise SystemExit("--call 必须是对象：{\"name\":..., \"input\":{...}}")
    name = str(row.get("name") or row.get("tool") or "").strip()
    if not name:
        raise SystemExit("--call 缺 name")
    payload = row.get("input")
    if payload is None:
        payload = row.get("args") or {}
    if not isinstance(payload, dict):
        raise SystemExit("--call 的 input/args 必须是对象")
    return {"name": name, "input": payload}


def _build_registry(cwd: str, *, with_write_store: bool):
    from tools.catalog import build_default_registry, inject_write_store

    reg = build_default_registry(cwd=cwd)
    note = ""
    if with_write_store:
        try:
            from engine.write_store import WriteStore

            inject_write_store(reg, WriteStore(cwd), "dryrun")
        except Exception as exc:  # noqa: BLE001 — 缺 write store 不挡只读工具
            note = f"write store 未接入: {exc}"
    return reg, note


def _flatten(metadata: dict[str, Any], prefix: str = "", depth: int = 2) -> dict[str, Any]:
    """展平嵌套元数据（浅两层）：判定字段常挂在 ``read_observation`` 这类子字典里。"""
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        name = f"{prefix}{key}"
        out[name] = value
        if isinstance(value, dict) and depth > 0:
            out.update(_flatten(value, prefix=f"{name}.", depth=depth - 1))
    return out


def _highlights(metadata: dict[str, Any] | None) -> list[str]:
    if not metadata:
        return []
    flat = _flatten(metadata)
    return [
        f"{key}={json.dumps(value, ensure_ascii=False, default=str)}"
        for key, value in flat.items()
        if key.split(".")[-1] in _HIGHLIGHT
    ]


def _dump_metadata(metadata: dict[str, Any] | None) -> str:
    if not metadata:
        return "{}"
    return json.dumps(metadata, ensure_ascii=False, default=str)


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    tail = max_chars - head
    return f"{text[:head]}\n…（省略 {len(text) - max_chars} 字符）…\n{text[-tail:]}"


async def _run_one(reg: Any, call: dict[str, Any], *, max_chars: int, timeout: float, index: int):
    from engine.abort import AbortController
    from msgtypes.message import ToolUse

    tool_use = ToolUse(id=f"dry{index}", name=call["name"], input=call["input"])
    controller = AbortController(label=f"dryrun:{call['name']}")
    result = await asyncio.wait_for(
        reg.run(tool_use, controller, skip_ask=True), timeout=timeout
    )
    return {
        "index": index,
        "name": call["name"],
        "input": call["input"],
        "is_error": bool(result.is_error),
        "status": str(result.status or ""),
        "error_kind": str(getattr(result, "error_kind", "") or ""),
        "retryable": bool(getattr(result, "retryable", False)),
        "metadata": dict(result.metadata or {}),
        "content": _clip(str(result.content or ""), max_chars),
        "content_chars": len(str(result.content or "")),
    }


def _print_row(row: dict[str, Any]) -> None:
    print(f"[{row['index']}] {row['name']} {json.dumps(row['input'], ensure_ascii=False)}")
    head = (
        f"is_error={row['is_error']} status={row['status']!r}"
        f" error_kind={row['error_kind']!r} retryable={row['retryable']}"
    )
    print(head)
    marks = _highlights(row["metadata"])
    if marks:
        print("fields: " + "  ".join(marks))
    print(f"metadata: {_dump_metadata(row['metadata'])}")
    print(f"content（{row['content_chars']} 字符）:")
    print(row["content"])
    print("-" * 72)


async def _main(args: argparse.Namespace) -> int:
    cwd = str(Path(args.cwd or ".").expanduser().resolve())
    reg, note = _build_registry(cwd, with_write_store=not args.no_write_store)
    if args.json and note:
        print(json.dumps({"note": note}, ensure_ascii=False), file=sys.stderr)
    elif note:
        print(f"[warn] {note}")

    if args.list:
        names = [str(t.name) for t in reg._tools.values()]  # noqa: SLF001 — dry-run 自查面
        print(f"cwd={cwd} surface={reg.tool_surface_id} count={len(names)}")
        for name in sorted(names):
            print(f"  {name}")
        return 0

    if args.describe:
        tool = reg.get(args.describe)
        if tool is None:
            print(f"unknown tool: {args.describe}", file=sys.stderr)
            return 2
        for schema in reg.schemas():
            if str(schema.get("name") or "") == args.describe:
                print(json.dumps(schema, ensure_ascii=False, indent=2))
                break
        print(f"concurrency_safe={getattr(tool, 'is_concurrency_safe', lambda: None)()}")
        return 0

    calls = [_parse_call(raw) for raw in (args.call or [])]
    if args.tool:
        calls.append({"name": args.tool, "input": json.loads(args.args or "{}")})
    if not calls:
        print("没有调用：给 --call / --tool，或用 --list / --describe", file=sys.stderr)
        return 2
    if args.dry:
        for row in calls:
            print(f"dry: {row['name']} {json.dumps(row['input'], ensure_ascii=False)}")
        return 0

    for index, call in enumerate(calls, start=1):
        try:
            row = await _run_one(
                reg, call, max_chars=args.max_chars, timeout=args.timeout, index=index
            )
        except asyncio.TimeoutError:
            print(f"[{index}] {call['name']} 超时（{args.timeout}s）")
            return 3
        if args.json:
            print(json.dumps(row, ensure_ascii=False))
        else:
            _print_row(row)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="工具面 dry-run（独立进程跑真实工具）")
    parser.add_argument("--cwd", default="", help="工作区根（缺省 = 当前目录）")
    parser.add_argument("--call", action="append", help='调用 JSON：{"name":...,"input":{...}}')
    parser.add_argument("--tool", help="单次调用的工具名（配合 --args）")
    parser.add_argument("--args", default="{}", help="--tool 的输入 JSON")
    parser.add_argument("--list", action="store_true", help="打印本进程的工具面")
    parser.add_argument("--describe", help="打印该工具的 schema 与并发声明")
    parser.add_argument("--json", action="store_true", help="逐条输出机器可读 JSON")
    parser.add_argument("--dry", action="store_true", help="只打调用面，不真跑")
    parser.add_argument("--no-write-store", action="store_true", help="不接 WriteStore")
    parser.add_argument(
        "--max-chars", type=int, default=1_200, help="content 打印上限（0 = 全文）"
    )
    parser.add_argument("--timeout", type=float, default=120.0, help="单次调用超时（秒）")
    args = parser.parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
