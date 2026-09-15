# -*- coding: utf-8 -*-
"""精确替换适配器：submit 传 multi_agent=True（env XEYO_MULTI_AGENT 可覆盖，默认开）。"""
import io
from pathlib import Path
p = Path("TerminalBench/xeyo_harbor_agent.py")
src = p.read_text(encoding="utf-8")

A = "        try:\n            async with aclosing(engine.submit(instruction)) as stream:\n"
assert src.count(A) == 1, f"submit 锚点不唯一: {src.count(A)}"
B = (
    "        # ⑥ 子 agent（Multi-Agent chip）：引擎侧读 options[\"multi_agent\"]，\n"
    "        # True 时在 T_now 挂 multi_agent_hint 块（tools/agent_tool/prompt.py），\n"
    "        # 让模型知道可以派子 agent；工具面本身一直有 Agent（catalog 评测档只裁 4 个）。\n"
    "        _ma = (os.environ.get(\"XEYO_MULTI_AGENT\", \"1\") or \"1\").strip().lower()\n"
    "        _multi_agent = _ma not in (\"0\", \"false\", \"no\", \"off\")\n"
    "        try:\n"
    "            async with aclosing(engine.submit(instruction, {\"multi_agent\": _multi_agent})) as stream:\n"
)
src = src.replace(A, B)

C = "  XEYO_REASONING_EFFORT 档位 low/high/max（默认 high；仅 thinking=enabled 时发出）\n"
assert src.count(C) == 1, f"docstring 锚点不唯一: {src.count(C)}"
src = src.replace(
    C,
    C + "  XEYO_MULTI_AGENT      子 agent 引导开关（默认 1=开；0 关闭 → 不挂 multi_agent_hint）\n",
)
p.write_text(src, encoding="utf-8")
print("已写入", p, "新字节数", len(src.encode('utf-8')))
