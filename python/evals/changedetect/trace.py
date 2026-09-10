"""trace —— L1：引擎决策轨迹（确定性重放）。

这一层盯的是**引擎在给定输入下的确定性行为**：注入了哪些块、注入了什么
文本、工具调用的顺序与形状、错误语义、轮次结构。

为什么这层也能"完美侦测"：驱动它的是 FakeModelClient（规则固定，无网络、
无采样），注入器 `run_pre_llm_inject` 是纯函数。同样的输入必然产出同样的
轨迹。所以它既没有随机性，也不需要花一分钱。

两个电池：
  inject  合成投影 × 注入上下文 → 捕获注入后的完整请求载荷
  loop    FakeModelClient 驱动的 query_loop → 捕获事件轨迹

分工：L0 管"文本改了没有"，L1 管"文本有没有真的被送出去、以什么顺序、
在什么条件下"。改一条 prompt 分支（比如给 Ask 模式加一句话）在这里必然
可见；L0 未必看得见（常量没变但装配条件变了）。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import canon

GOLDEN_DIR = Path(__file__).resolve().parent / "goldens"


# --------------------------------------------------------------------------
# 投影构造辅助
# --------------------------------------------------------------------------


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _read_use(call_id: str, path: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": call_id,
                "name": "Read",
                "input": {"file_path": path},
            }
        ],
    }


def _tool_result(call_id: str, text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": text,
                "is_error": is_error,
            }
        ],
    }


def _bash_use(call_id: str, command: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": call_id,
                "name": "Bash",
                "input": {"command": command},
            }
        ],
    }


PLAIN: list[dict[str, Any]] = [_user("把这个仓库的结构讲一下。")]

AFTER_TOOLS: list[dict[str, Any]] = [
    _user("读一下 README。"),
    _read_use("call_demo1", "<REPO>/README.md"),
    _tool_result("call_demo1", "# XEYO\n\n本地编码 Agent。"),
]

AFTER_FAILED_TOOL: list[dict[str, Any]] = [
    _user("读一下不存在的文件。"),
    _bash_use("call_demo2", "cat /nope/missing.txt"),
    _tool_result("call_demo2", "cat: /nope/missing.txt: No such file", is_error=True),
]


# --------------------------------------------------------------------------
# inject 电池
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class InjectScenario:
    id: str
    projected: list[dict[str, Any]]
    ctx: dict[str, Any]
    mode: str = ""


def _inject_scenarios(tmp: Path) -> list[InjectScenario]:
    nested_dir = tmp / "pkg"
    nested_dir.mkdir(parents=True, exist_ok=True)
    nested_md = nested_dir / "XEYO.md"
    nested_md.write_text(
        "# 子目录规则（changedetect 固定样本）\n- 只回答数字。\n",
        encoding="utf-8",
        newline="\n",
    )
    nested_projected: list[dict[str, Any]] = [
        _user("继续改这个子目录。"),
        _read_use("call_demo3", str(nested_md)),
        _tool_result("call_demo3", nested_md.read_text(encoding="utf-8")),
    ]

    from engine.budget import BudgetTracker

    return [
        InjectScenario("plain", PLAIN, {}),
        InjectScenario("after_tools", AFTER_TOOLS, {}),
        InjectScenario("after_failed_tool", AFTER_FAILED_TOOL, {}),
        InjectScenario("wrap_up", PLAIN, {"forced_wrap_up": True}),
        InjectScenario("runtime_notice", PLAIN, {"runtime_notice": "turn 8/10"}),
        InjectScenario("runtime_notice_after_tools", AFTER_TOOLS,
                       {"runtime_notice": "turn 9/10"}),
        InjectScenario("multi_agent", PLAIN, {"multi_agent": True}),
        InjectScenario("goal", PLAIN, {"goal": "把 CLI 的 --json 输出补齐。"}),
        InjectScenario(
            "approved_plan",
            PLAIN,
            {"approved_plan": "1. 读 registry\n2. 加字段\n3. 跑测试"},
        ),
        InjectScenario(
            "approved_plan_pointer",
            PLAIN,
            {"approved_plan": "1. 读 registry\n2. 加字段", "plan_pointer": True},
        ),
        InjectScenario("subagent", AFTER_TOOLS, {"subagent": True}),
        InjectScenario("wrap_up_after_tools", AFTER_TOOLS, {"forced_wrap_up": True}),
        InjectScenario(
            "channel_legacy",
            PLAIN,
            {"forced_wrap_up": True, "runtime_notice": "turn 5/8", "strategy": "legacy"},
        ),
        InjectScenario(
            "channel_env",
            PLAIN,
            {"forced_wrap_up": True, "runtime_notice": "turn 5/8", "strategy": "env_channel"},
        ),
        InjectScenario("no_instructions", PLAIN, {"include_memory_index": False}),
        InjectScenario("instructions_on", nested_projected, {}),
        InjectScenario(
            "instructions_off", nested_projected, {"inject_instructions": False}
        ),
        InjectScenario("plan_mode", PLAIN, {}, mode="plan"),
        InjectScenario("ask_mode", PLAIN, {}, mode="ask"),
        InjectScenario(
            "budget_mirror",
            PLAIN,
            {"budget": BudgetTracker(max_turns=3, max_tool_calling=2)},
        ),
    ]


def _run_inject_scenario(sc: InjectScenario) -> str:
    from permissions.policy import set_agent_mode
    from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

    set_agent_mode(sc.mode or None)
    try:
        ctx = InjectContext(**sc.ctx)
        out = run_pre_llm_inject([dict(m) for m in sc.projected], ctx)
    finally:
        set_agent_mode(None)
    return canon.canon_obj(out) + "\n"


def collect_inject_traces() -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="xeyo_cd_inject_") as raw:
        tmp = Path(raw).resolve()
        # 临时目录名随机 → 登记为字面量，否则 golden 每次都会"变"
        canon.register_literal(str(tmp), "<TMP>")
        for variant in (str(tmp).replace("\\", "/"), str(tmp).replace("/", "\\")):
            canon.register_literal(variant, "<TMP>")
        out: dict[str, str] = {}
        for sc in _inject_scenarios(tmp):
            try:
                out[f"inject/{sc.id}"] = _run_inject_scenario(sc)
            except Exception as exc:  # noqa: BLE001 — 抛错本身就是要被侦测的行为
                out[f"inject/{sc.id}"] = f"<raised {type(exc).__name__}: {exc}>\n"
        return out


# --------------------------------------------------------------------------
# loop 电池
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopScenario:
    id: str
    history: list[tuple[str, str]]
    use_echo: bool = False
    max_turns: int = 4


LOOP_SCENARIOS: tuple[LoopScenario, ...] = (
    LoopScenario("echo_roundtrip", [("user", "echo:hi")], use_echo=True),
    LoopScenario("echo_empty", [("user", "echo:")], use_echo=True),
    LoopScenario("plain_text", [("user", "只回一个字：好")]),
    LoopScenario("multi_turn", [("user", "echo:one"), ("assistant", "echoed: one")],
                 use_echo=True),
)


async def _run_loop_scenario(sc: LoopScenario) -> str:
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from model.fake import FakeModelClient
    from msgtypes.message import user_message
    from prompt.assembler import DEFAULT_SYSTEM, PromptAssembler
    from session.message_store import MessageStore
    from tools.echo import EchoTool
    from tools.tool_registry import ToolRegistry

    msgs = []
    for role, text in sc.history:
        msg = user_message(text)
        if role == "assistant" and isinstance(msg.get("content"), str):
            msg = dict(msg)
            msg["role"] = "assistant"
        msgs.append(msg)

    registry = ToolRegistry()
    if sc.use_echo:
        registry.register(EchoTool())

    events: list[str] = []
    assistant_chars = 0
    final = ""
    async for ev in query_loop(
        store=MessageStore(msgs),
        model=FakeModelClient(),
        tools=registry,
        prompt=PromptAssembler(),
        system_prompt=DEFAULT_SYSTEM,
        abort=AbortController(),
        budget=BudgetTracker(max_turns=sc.max_turns),
    ):
        name = type(ev).__name__
        if name == "ToolCallEvent":
            events.append(f"ToolCall:{getattr(ev, 'name', '?')}")
        elif name == "ToolResultEvent":
            err = bool(getattr(ev, "is_error", False))
            events.append(f"ToolResult{'!' if err else ''}")
        elif name == "FinalEvent":
            final = str(getattr(ev, "text", ""))
            events.append("Final")
        elif name == "AssistantDelta":
            assistant_chars += len(str(getattr(ev, "text", "")))
        else:
            events.append(name)

    # 压缩连续同类事件，避免逐字流把轨迹淹掉，同时保留轮次结构
    compressed: list[str] = []
    for item in events:
        if compressed and compressed[-1] == item:
            continue
        compressed.append(item)

    payload = {
        "id": sc.id,
        "tools": sorted(t for t in [s.get("name") for s in registry.schemas()] if t),
        "events": compressed,
        "final": final,
        "assistant_chars": assistant_chars,
    }
    return canon.canon_obj(payload) + "\n"


def collect_loop_traces() -> dict[str, str]:
    out: dict[str, str] = {}
    for sc in LOOP_SCENARIOS:
        try:
            out[f"loop/{sc.id}"] = asyncio.run(_run_loop_scenario(sc))
        except Exception as exc:  # noqa: BLE001
            out[f"loop/{sc.id}"] = f"<raised {type(exc).__name__}: {exc}>\n"
    return out


BATTERIES: dict[str, Any] = {
    "inject": collect_inject_traces,
    "loop": collect_loop_traces,
}


def collect(batteries: set[str] | None = None) -> dict[str, str]:
    """跑指定电池，返回 name → 规范化轨迹文本。"""
    names = sorted(batteries or set(BATTERIES))
    out: dict[str, str] = {}
    for name in names:
        fn = BATTERIES.get(name)
        if fn is None:
            raise KeyError(f"未知电池：{name}（可选 {sorted(BATTERIES)}）")
        out.update(fn())
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------
# golden 读写与比对
# --------------------------------------------------------------------------


def _path_for(directory: Path, name: str) -> Path:
    return directory / "trace" / f"{canon.safe_name(name)}.txt"


def write_golden(traces: dict[str, str], *, directory: Path = GOLDEN_DIR) -> Path:
    target = directory / "trace"
    target.mkdir(parents=True, exist_ok=True)
    keep: set[str] = set()
    for name, text in traces.items():
        fname = f"{canon.safe_name(name)}.txt"
        keep.add(fname)
        (target / fname).write_text(
            canon.canon_text(text), encoding="utf-8", newline="\n"
        )
    for stale in target.glob("*.txt"):
        if stale.name not in keep:
            stale.unlink()
    index = {
        name: {"sha256": canon.sha(canon.canon_text(text)), "chars": len(text)}
        for name, text in traces.items()
    }
    path = directory / "trace_index.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "generated_by": "evals.changedetect.trace",
                "traces": index,
            },
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def load_golden(*, directory: Path = GOLDEN_DIR) -> dict[str, str]:
    target = directory / "trace"
    if not target.is_dir():
        return {}
    return {
        p.stem: p.read_text(encoding="utf-8") for p in sorted(target.glob("*.txt"))
    }


def compare(
    traces: dict[str, str],
    *,
    directory: Path = GOLDEN_DIR,
    max_diff_chars: int = 4000,
) -> list[dict[str, Any]]:
    from .surface import Change

    golden = load_golden(directory=directory)
    changes: list[dict[str, Any]] = []
    for name, text in sorted(traces.items()):
        key = canon.safe_name(name)
        after = canon.canon_text(text)
        before = golden.get(key)
        if before is None:
            changes.append(
                Change(name=name, status="added", group="trace",
                       chars_after=len(after),
                       blurb="新增轨迹场景").to_dict()
            )
            continue
        if before == after:
            continue
        added, removed = canon.char_delta(before, after)
        changes.append(
            Change(
                name=name,
                status="modified",
                group="trace",
                chars_before=len(before),
                chars_after=len(after),
                added=added,
                removed=removed,
                first_line=canon.first_diff_line(before, after),
                diff=canon.shorten(
                    canon.unified(before, after, name), max_diff_chars
                ),
            ).to_dict()
        )
    for key in sorted(set(golden) - {canon.safe_name(n) for n in traces}):
        changes.append(
            Change(name=key, status="removed", group="trace",
                   chars_before=len(golden[key]),
                   blurb="轨迹场景已消失").to_dict()
        )
    return changes
