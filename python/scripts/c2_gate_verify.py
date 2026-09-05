"""c2_gate_verify — 合成会话验证 Path A 三个网格维度是否真正影响 C2 决策。

不读真录、零费用。构造一个「尾部增长型」会话（大量大 tool_result），分别切换
pressure/save/tail 的公式覆盖，看 C2 边界推进是否随维度变化（证明三维度已真正接线）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _build_history(n_turns: int = 40, chunk: int = 9000) -> list[dict]:
    msgs: list[dict] = [{"role": "user", "content": "start"}]
    for i in range(n_turns):
        msgs.append(
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": f"g{i}", "name": "Grep", "input": {"q": "x"}}],
            }
        )
        content = ("pattern hit\n" + "x" * chunk) if chunk else "x"
        msgs.append(
            {
                "role": "tool",
                "tool_call_id": f"g{i}",
                "name": "Grep",
                "content": [{"type": "tool_result", "tool_use_id": f"g{i}", "content": content, "is_error": False}],
            }
        )
    return msgs


def _run(messages: list[dict], *, pressure: float | None, save: float | None, tail: float | None,
         per_turn: float | None = None) -> int:
    import memory.runtime as rt
    from memory.working import WorkingSnapshot

    rt.l5_mode = lambda: "v61"
    # 开三个公式开关（一次性 override，不改生产设置）
    os.environ["XEYO_C2_FORMULA_OVERRIDE"] = (
        "XEYO_C2_PRESSURE_FORMULA:1,XEYO_C2_GAIN_FORMULA:1,XEYO_C2_EXTEND_FORMULA:1"
    )
    def _set(name: str, v):  # noqa: ANN001
        if v is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = str(v)

    _set("XEYO_C2_PRESSURE_RATIO", pressure)
    _set("XEYO_C2_SAVE_RATIO", save)
    _set("XEYO_C2_TAIL_BUDGET_TOKENS", tail)
    _set("XEYO_C2_PER_TURN_TOKENS", per_turn)

    w = WorkingSnapshot()
    w.turns_since_c2 = 99  # 冷却放行，专注 C2 触发
    last = 0
    adv = 0
    call_idxs = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    for idx in call_idxs:
        try:
            rt.project_for_model(messages[: idx], w, remaining_turns=8, include_memory_index=False)
        except Exception:  # noqa: BLE001
            continue
        if int(w.compact_cursor or 0) != last:
            adv += 1
            last = int(w.compact_cursor or 0)

    for k in ("XEYO_C2_FORMULA_OVERRIDE", "XEYO_C2_PRESSURE_RATIO", "XEYO_C2_SAVE_RATIO",
              "XEYO_C2_TAIL_BUDGET_TOKENS", "XEYO_C2_PER_TURN_TOKENS"):
        os.environ.pop(k, None)
    rt.l5_mode = lambda: "project"
    return adv


def main() -> int:
    msgs = _build_history(n_turns=40, chunk=9000)
    base = _run(msgs, pressure=None, save=None, tail=None)
    p055 = _run(msgs, pressure=0.55, save=None, tail=None)
    p070 = _run(msgs, pressure=0.70, save=None, tail=None)
    s030 = _run(msgs, pressure=None, save=0.30, tail=None)
    s040 = _run(msgs, pressure=None, save=0.40, tail=None)
    t12000 = _run(msgs, pressure=None, save=None, tail=12000)
    t32000 = _run(msgs, pressure=None, save=None, tail=32000)

    print("# 合成会话（40 轮 × 9KB tool_result）C2 边界推进数")
    print(f"  基线(公式关, 但有压力门)        = {base}")
    print(f"  pressure=0.55                  = {p055}")
    print(f"  pressure=0.70                  = {p070}")
    print(f"  save=0.30                      = {s030}")
    print(f"  save=0.40                      = {s040}")
    print(f"  tail=12000                     = {t12000}")
    print(f"  tail=32000                     = {t32000}")

    print("\n# 判定（三维是否真正接线）")
    ok_p = p055 != p070 or (p055 != base)
    ok_s = s030 != s040 or (s030 != base)
    ok_t = t12000 != t32000 or (t12000 != base)
    p_res = "OK" if ok_p else "DEGENERATE"
    s_res = "OK" if ok_s else "DEGENERATE"
    t_res = "OK" if ok_t else "DEGENERATE"
    print(f"  pressure 维度 {p_res}  ({p055} vs {p070})")
    print(f"  save     维度 {s_res}  ({s030} vs {s040})")
    print(f"  tail     维度 {t_res}  ({t12000} vs {t32000})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
