"""fileio 文本族随机往返性质测试（种子确定，seed=20261005）。

为什么加：这一族是历史缺陷高发区（CRLF 匹配 / BOM 保真 / 引号风格 / 孤立 \\r
都有过实测事故）。上例化用例只证"手挑的那几种"，这里用固定种子的随机语料
把四条契约连起来钉：

1. read(write(T, E, enc)) 的正文 == normalize_newlines(T)；
2. 正文含换行时，read 报回的 endings == 写入时的 E（无换行=无可判，跳过）；
3. 幂等写回：按 read 报回的 (text, endings, encoding) 重写一次，字节逐位不变；
4. LF 归一化后的探测串出现在正文里 ⇒ find_actual_string 必命中（CRLF/弯引号
   变体由实现内部归一，不允许静默漏配）。

断言全部可证伪：任何一条不成立即红，并打印反例参数（case/期望/实际）。
"""

from __future__ import annotations

import random

from tools.fileio.text import (
    find_actual_string,
    normalize_newlines,
    read_text_file,
    write_text_file,
)

_SEED = 20261005
_CASES = 200
_ALPHA = [
    "a", "b", "Z", "中", "文", "🙂", "\n", "\r\n", "\r", "\"", "'",
    "\u201c", "\u201d", "\u2018", "\u2019", "\t", " ", ".", "\\",
]


def _gen_text(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(_ALPHA) for _ in range(n))


def test_fileio_roundtrip_properties(tmp_path) -> None:
    rng = random.Random(_SEED)
    fails: list[tuple] = []
    for case in range(_CASES):
        text_in = _gen_text(rng, rng.randint(1, 40))
        endings = rng.choice(["LF", "CRLF"])
        encoding = rng.choice(["utf-8", "utf-8-sig", "utf-16-le"])
        path = str(tmp_path / f"c{case}.txt")
        try:
            write_text_file(path, text_in, encoding=encoding, line_endings=endings)
        except UnicodeEncodeError:
            continue  # 码页表示不了（如 gbk+emoji）属契约内拒绝
        text, got_endings, got_encoding = read_text_file(path)
        norm = normalize_newlines(text_in)

        if text != norm:
            fails.append((case, "content", repr(text_in), repr(text)))
            continue
        if "\n" in norm and got_endings != endings:
            fails.append((case, "endings", repr(text_in), got_endings, endings))
            continue

        with open(path, "rb") as fh:
            b1 = fh.read()
        write_text_file(
            path, text, encoding=got_encoding, line_endings=got_endings
        )
        with open(path, "rb") as fh:
            b2 = fh.read()
        if b1 != b2:
            fails.append((case, "idempotent", repr(text_in)))
            continue

        probe = _gen_text(rng, rng.randint(1, 6))
        if normalize_newlines(probe) in norm:
            if find_actual_string(norm, probe) is None:
                fails.append((case, "find", repr(norm), repr(probe)))
                continue

    assert not fails, f"随机往返反例（seed={_SEED}）：{fails[:8]}"


def test_probe_generator_actually_varies() -> None:
    """方向控制：语料必须真的混合换行/引号族，否则上面的循环是空转。"""
    rng = random.Random(_SEED)
    buf = "".join(_gen_text(rng, 30) for _ in range(20))
    assert "\r\n" in buf and "\n" in buf and "\r" in buf
    assert "\u201c" in buf or "\u201d" in buf
    assert any(ch in buf for ch in ("中", "文", "🙂"))


def test_find_actual_string_matches_quote_and_crlf_variants() -> None:
    """命中侧：引号/行尾形态与正文不一致时也必须找到，并返回**文件里的**变体。

    契约：``file_content`` 是 read_text_file 的 LF 归一产物；搜索串可以是模型
    手打的直引号 + CRLF，正文可能是人写的弯引号。
    """
    from tools.fileio.text import normalize_quotes

    rng = random.Random(5201314)
    checked = 0
    for case in range(200):
        content = normalize_newlines(_gen_text(rng, rng.randint(10, 60)))
        if len(content) < 8:
            continue
        i = rng.randint(0, len(content) - 6)
        frag = content[i : i + rng.randint(4, 14)]
        swapped = "".join(
            rng.choice(["\u201c", "\""]) if ch == "\"" else
            rng.choice(["\u201d", "\""]) if ch == "\u201d" else
            rng.choice(["'", "\u2018"]) if ch == "'" else
            rng.choice(["'", "\u2019"]) if ch == "\u2019" else ch
            for ch in frag
        )
        if "\n" in swapped and rng.random() < 0.5:
            swapped = swapped.replace("\n", "\r\n")
        got = find_actual_string(content, swapped)
        assert got is not None, (case, repr(swapped), repr(content))
        assert got in content, (case, repr(got))
        assert normalize_quotes(got) == normalize_quotes(normalize_newlines(swapped)), (
            case, repr(got), repr(swapped),
        )
        checked += 1
    assert checked > 100, f"样本太少（{checked}），空转"


def test_find_actual_string_has_no_false_positives() -> None:
    """miss 侧：引号归一后仍不匹配的搜索必须返回 None（假阳护栏）。"""
    from tools.fileio.text import normalize_quotes

    rng = random.Random(998877)
    misses = 0
    for case in range(200):
        content = normalize_newlines(_gen_text(rng, rng.randint(10, 60)))
        search = normalize_newlines(_gen_text(rng, rng.randint(5, 12)))
        if normalize_quotes(search) in normalize_quotes(content):
            continue  # 恰巧命中 ⇒ 不入 miss 池
        misses += 1
        assert find_actual_string(content, search) is None, (
            case, repr(search), repr(content)
        )
    assert misses > 50, f"miss 样本太少（{misses}），该用例空转"
