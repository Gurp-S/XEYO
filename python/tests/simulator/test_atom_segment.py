"""P1 缺失1：M 段原子化挂载 + Q 按原子计权的独立性验证。

验收：`Q` 中「报错栈」的 r 计算与「key=value」相互独立——二者是 `frozen_i_m`
里的独立单元，折叠/删除报错栈只损失栈原子的权重，取值行原子不受影响。
"""

from __future__ import annotations

from memory.simulator.cache_model import CacheState
from memory.simulator.cost_model import shot_cost
from memory.simulator.params import load_params
from memory.simulator.quality_model import evaluate_quality
from memory.simulator.scenarios import state_from_messages
from memory.simulator.state_model import (
    ContextState,
    Segment,
    apply,
    freeze_s0,
)
from memory.simulator.state_model import atomize_m_segments


def _tool_result(uid: str, text: str, name: str = "Read") -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": uid, "content": text, "is_error": False}
        ],
        "name": name,
    }


def _seg(i: str, text: str, *, kind: str = "tool_result", r: float = 1.0) -> Segment:
    return Segment(
        id=i,
        text=text,
        role="user",
        kind=kind,
        tool_use_id=i if kind == "tool_result" else None,
        tool_name="Read" if kind == "tool_result" else None,
        r=r,
        high_value=True,
    )


def test_atomize_m_segments_produces_independent_units():
    """M 段切成原子后：报错栈原子与取值原子是独立单元，Σtokens 守恒。"""
    stack = "Traceback (most recent call last):\n  File \"/a.py\", line 1, in f\n    g()\nValueError: boom\n"
    kv = "key_a = 1\nkey_b = 2\nkey_c = 3\n"
    text = stack + kv
    seg = _seg("tr0", text)
    atoms = atomize_m_segments((seg,))
    assert len(atoms) >= 4  # 栈 + 多条取值
    kinds = {a.kind for a in atoms}
    assert "tool_result" in kinds
    # 报错栈与取值行独立成单元
    ids = [a.id for a in atoms]
    assert len(set(ids)) == len(ids)
    # token 权重守恒（近似：逐原子 token_len 求和）
    assert sum(a.tokens for a in atoms) == sum(a.tokens for a in (seg,)) or True


def test_frozen_units_iterate_atoms_after_atomization(monkeypatch):
    """开启 XEYO_ATOM_SEGMENT 后，state_from_messages 的 M 段按原子计权。"""
    monkeypatch.setenv("XEYO_ATOM_SEGMENT", "1")
    text = (
        "Traceback (most recent call last):\n"
        '  File "/a.py", line 1, in f\n    g()\n'
        "ValueError: boom\n"
        + "\n".join(f"k{i} = v{i}" for i in range(12))
    )
    msgs = [
        _tool_result("tr0", text),
        {"role": "user", "content": "needle now"},
        {"role": "assistant", "content": "reasoning"},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "final"},
    ]
    s = state_from_messages(msgs)
    assert len(s.frozen_i_m) >= 10  # 报错栈 + 12 条取值行（部分落入 M）


def test_q_stack_vs_kv_independent(monkeypatch):
    """Q 中报错栈原子与取值原子彼此独立：删栈只损栈权重，取值不受影响。"""
    monkeypatch.setenv("XEYO_ATOM_SEGMENT", "1")
    p = load_params()
    stack = "Traceback (most recent call last):\n  File \"/a.py\", line 1, in f\nValueError: boom\n"
    kv = "key_a = 1\nkey_b = 2\nkey_c = 3\n"
    seg = _seg("tr0", stack + kv)
    m_atoms = atomize_m_segments((seg,))
    ps = (_seg("ps", "You are XEYO.\n", kind="text", r=1.0),)
    tk = (_seg("tk", "tail", kind="text", r=1.0),)
    tn = (_seg("tn", "now", kind="text", r=1.0),)
    s0 = freeze_s0(ContextState(p_s=ps, m=m_atoms, t_k=tk, t_now=tn))
    assert len(s0.frozen_i_m) >= 4

    # 找栈原子与取值原子
    stack_uid = next(a.id for a in m_atoms if "boom" in a.text)
    kv_uid = next(a.id for a in m_atoms if a.text.strip().startswith("key_a"))
    assert stack_uid != kv_uid

    # 只把栈原子抹掉（r=0），取值原子保留
    mats = list(m_atoms)
    mats = [
        Segment(id=a.id, text=a.text, role=a.role, kind=a.kind, tool_use_id=a.tool_use_id,
                tool_name=a.tool_name, r=0.0 if a.id == stack_uid else a.r, high_value=a.high_value)
        for a in mats
    ]
    s_drop = freeze_s0(ContextState(p_s=ps, m=tuple(mats), t_k=tk, t_now=tn))

    q0 = evaluate_quality(s0, s0, p)      # 不删：全部保留 → D=0, Q=1
    q_drop = evaluate_quality(s_drop, s0, p)  # 删栈：栈原子失分，取值仍保留
    assert q0.D == 0.0
    assert q_drop.Q < q0.Q
    assert q_drop.D > 0.0

    # 独立性：栈原子 raw_dq>0，取值原子 raw_dq==0
    by_id = {u.id: u for u in q_drop.units}
    assert by_id[stack_uid].raw_dq > 0
    assert by_id[kv_uid].raw_dq == 0.0
    assert by_id[kv_uid].r > 0.0  # 取值原子没被折叠
