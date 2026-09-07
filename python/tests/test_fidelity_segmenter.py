"""P1 缺失1：原子事实分段 fidelity_segmenter 单测。

验收（见交接提示词）：
- 一条含 Traceback+key=value 的 8KB 结果 → ``split_into_atoms`` ≥10 个原子。
- ``Σv_i == |M|``（== len(original_text)，精确划分）。
- ``Q`` 中「报错栈」的 r 计算与「key=value」相互独立（原子级单元，见 state_model 挂载）。
"""

from __future__ import annotations


from memory.fidelity_segmenter import (
    Atom,
    atoms_enabled,
    atoms_to_dicts,
    split_into_atoms,
)


def _traceback_block() -> list[str]:
    lines = ["Traceback (most recent call last):"]
    for i in range(4):
        lines.append(f'  File "/work/app.py", line {i + 1}, in step{i}')
        lines.append("    do_work(x)")
    lines.append("ValueError: bad value")
    return lines


def _kv_lines(n: int) -> list[str]:
    return [f"key_{i} = value{i}_xyz" for i in range(n)]


def make_8k() -> str:
    """8KB 混合文本：栈回溯 + 12 条 key=value + 一点散文，末尾补齐到 8192 字符。"""
    chunk = "\n".join(_traceback_block() + _kv_lines(12) + ["some trailing prose line"])
    # 补齐到恰好 8192
    pad = 8192 - len(chunk)
    assert pad > 0
    return chunk + ("x" * pad)


def test_empty_and_blanks():
    assert split_into_atoms("") == ()
    assert split_into_atoms("\n\n")  # not empty; blanks are atoms
    a = split_into_atoms("\n\n")
    assert sum(x.weight for x in a) == 2


def test_acceptance_8k_atoms_and_partition():
    text = make_8k()
    assert len(text) == 8192
    atoms = split_into_atoms(text)
    assert len(atoms) >= 10
    assert sum(a.weight for a in atoms) == 8192  # Σv_i == |M|
    # 无缝无重叠
    assert atoms[0].start == 0
    assert atoms[-1].end == 8192
    for prev, cur in zip(atoms, atoms[1:]):
        assert prev.end == cur.start
    # 报错栈与取值行各成独立单元
    assert any(a.kind == "stack" for a in atoms)
    assert sum(1 for a in atoms if a.kind == "kv") >= 10


def test_atom_fields():
    a = split_into_atoms("a=1\nb=2\n")
    for atom in a:
        assert isinstance(atom, Atom)
        assert atom.weight == len(atom.text) == atom.end - atom.start
    assert a[0].kind == "kv"
    assert a[0].text == "a=1\n"


def test_oversize_line_chunked():
    long_line = "k = " + ("Z" * 2000) + "\n"
    atoms = split_into_atoms(long_line)
    assert sum(x.weight for x in atoms) == len(long_line)
    assert any(x.kind == "chunk" for x in atoms)
    assert len(atoms) >= 4  # >512 → multiple chunks


def test_atoms_to_dicts_compact():
    atoms = split_into_atoms("a=1\nb=2\n")
    d = atoms_to_dicts(atoms, text_cap=8)
    assert all("weight" in x and "kind" in x and "text" in x for x in d)
    assert all(len(x["text"]) <= 9 for x in d)  # 8 + ellipsis


def test_gate_default_off():
    # 默认不开启（保持默认 project 路径字节稳定）
    assert atoms_enabled() is False


def test_gate_env(monkeypatch):
    monkeypatch.setenv("XEYO_ATOM_SEGMENT", "1")
    assert atoms_enabled() is True
