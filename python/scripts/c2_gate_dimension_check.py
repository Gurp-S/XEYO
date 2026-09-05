"""c2_gate_dimension_check — 直接验证 Path A 三个维度都影响 C2 触发判定。

合成会话太粗（adv 是整数、采样粗），读真录太重。本脚本直接对「单个 call」判定
各维度是否改变 C2 触发结果，用可控的 messages 切片 + 直接调用 _c2_gain_enough /
_c2_pressure_ratio。零费用、零真录。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _msgs(n: int, chunk: int = 9000) -> list[dict]:
    msgs: list[dict] = [{"role": "user", "content": "start"}]
    for i in range(n):
        msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"g{i}", "name": "Grep", "input": {"q": "x"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"g{i}", "name": "Grep",
                     "content": [{"type": "tool_result", "tool_use_id": f"g{i}", "content": "hit\n" + "y" * chunk, "is_error": False}]})
    return msgs


def main() -> int:
    import memory.runtime as rt
    from memory.simulator.params import load_params
    from memory.working import WorkingSnapshot

    os.environ["XEYO_C2_FORMULA_OVERRIDE"] = "XEYO_C2_GAIN_FORMULA:1,XEYO_C2_PRESSURE_FORMULA:1"
    orig_l5 = rt.l5_mode
    rt.l5_mode = lambda: "v61"

    def _set(name, v):
        if v is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = str(v)
        return os.environ.get(name)

    msgs = _msgs(40)
    w = WorkingSnapshot(); w.turns_since_c2 = 99
    p = load_params()
    new_cursor = 40  # 前 39 条压为摘要，留尾部

    # 1) save 维度：直接调 _c2_gain_enough，看 save=0.30 vs 0.40 是否改变结果
    def gain(save):
        w.c2_summary_text = ""  # 强制走确定性摘要
        _set("XEYO_C2_SAVE_RATIO", save)
        return rt._c2_gain_enough(msgs, w, new_cursor, p, remaining_turns=8)

    _set("XEYO_C2_SAVE_RATIO", None)
    base_gain = gain(None)
    g30 = gain(0.30)
    g40 = gain(0.40)
    print(f"save 维度: base={base_gain}  0.30={g30}  0.40={g40}  → "
          f"{'OK' if g30 != g40 else 'DEGENERATE'}")

    # 2) pressure 维度：_c2_pressure_ratio 在 pressure 覆盖下是否改变
    def pressure_ratio(pressure=None, tail=None):
        _set("XEYO_C2_PRESSURE_RATIO", pressure)
        _set("XEYO_C2_TAIL_BUDGET_TOKENS", tail)
        return rt._c2_pressure_ratio(w, p)

    _set("XEYO_C2_PRESSURE_RATIO", None); _set("XEYO_C2_TAIL_BUDGET_TOKENS", None)
    pr_base = pressure_ratio()
    pr_062 = pressure_ratio(0.62)
    pr_070 = pressure_ratio(0.70)
    pr_tail = pressure_ratio(None, 32000)
    print(f"pressure 维度: base={pr_base:.4f}  0.62={pr_062:.4f}  0.70={pr_070:.4f}  → "
          f"{'OK' if pr_062 != pr_070 else 'DEGENERATE'}")
    print(f"tail 维度(无 pressure 覆盖): base={pr_base:.4f}  tail32000={pr_tail:.4f}  → "
          f"{'OK' if abs(pr_tail - pr_base) > 1e-6 else 'DEGENERATE'}")

    for k in ("XEYO_C2_FORMULA_OVERRIDE", "XEYO_C2_SAVE_RATIO", "XEYO_C2_PRESSURE_RATIO", "XEYO_C2_TAIL_BUDGET_TOKENS"):
        os.environ.pop(k, None)
    rt.l5_mode = orig_l5

    # 3) tail 在压力门里确实改变触发器：pressure 无覆盖时，尾预算大 → 压力比小 → 更早触发
    print("\n# note: tail 通过 _c2_pressure_ratio 影响压力门；pressure 覆盖下 tail 被 env 直接取代。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
