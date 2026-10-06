"""content 行解析/渲染随机性质测试（种子确定，seed=31337）。

覆盖两种载体形态（`--null` 主机形态与旧式文本形态）的四条契约：

1. **NUL 形态保真**：``path\\0num[-:]content`` 解析出的四个字段逐字节等于构造值
   （content 任意含 ``:``/``-``/数字/引号——NUL 定界就是为了消灭歧义）；
2. **渲染无 NUL 且文本保真**：相对化输出不含 NUL，且对别名安全（路径+接缝无
   ``[-:]\\d+[-:]`` 序列）的行，重解析字段守恒；
3. **旧式文本形态**（无冒号/数字路径）`path{sep}num{sep}content` 解析守恒；
4. **count 行相对化对相对路径是恒等**（不误改）。

已知边界（都属"旧式文本形态固有歧义"，不是本测试的失败条件）：
- 路径内 ``-12-``/``:12:`` 序列会被当成行号位（NUL 形态无此问题）；
- **`-` 分隔的上下文行若 content 含 ``:数字:``（如时间戳 ``12:30:00``），
  冒号形态会被抢先解析**——模型可见文本因"字符串手术恒等式"不受损，但排序键
  的 path/num 取错。已 strict xfail 在册（修法待拍：容器回退改发 NUL 等）。
"""

from __future__ import annotations

import random
import re

import pytest

from tools.fileio.paths import to_relative_path
from tools.grep_tool.grep_tool import (
    _parse_content_line,
    _relativize_content_line,
    _relativize_count_line,
)

_SEED = 31337
_CASES = 200
_ALPHA = ["a", "Z", "中", "文", ".", "_", "-", ":", "0", "5", "\\", "/", " ", "🙂", "'", '"']
_SEP_AMB = re.compile(r"[-:]\d+[-:]")


def _gen(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(_ALPHA) for _ in range(n))


def test_nul_form_roundtrip_is_lossless(tmp_path) -> None:
    base = str(tmp_path)
    rng = random.Random(_SEED)
    fails: list[tuple] = []
    for case in range(_CASES):
        path = "sub/" + _gen(rng, rng.randint(1, 8)).replace(":", "_").replace("\\", "_")
        num = rng.randint(1, 9999)
        sep = rng.choice([":", "-"])
        content = _gen(rng, rng.randint(0, 30)).replace("\0", "").replace("\n", "")
        line = f"{path}\0{num}{sep}{content}"
        parsed = _parse_content_line(line)
        if parsed is None or parsed != (path, num, sep, content):
            fails.append((case, (path, num, sep, content), parsed))
            continue
        rel = _relativize_content_line(line, base)
        if "\0" in rel:
            fails.append((case, "nul-leak", repr(rel)))
            continue
        if not _SEP_AMB.search(path + sep):
            rp, rn, rs, rc = _parse_content_line(rel) or (None, None, None, None)
            if (rn, rs, rc) != (num, sep, content):
                fails.append((case, "reparse-fields", (num, sep, content), (rn, rs, rc), rel))
    assert not fails, f"NUL 形态反例（seed={_SEED}）：{fails[:6]}"


def test_legacy_text_form_roundtrip_alias_free(tmp_path) -> None:
    rng = random.Random(_SEED + 1)
    fails: list[tuple] = []
    for case in range(_CASES):
        tpath = "sub/" + re.sub(
            r"\d", "", _gen(rng, rng.randint(1, 8)).replace(":", "").replace("\\", "")
        )
        num = rng.randint(1, 9999)
        sep = rng.choice([":", "-"])
        content = _gen(rng, rng.randint(0, 30)).replace("\0", "").replace("\n", "")
        if sep == "-" and re.search(r":\d+:", content):
            continue  # 已知抢位类，由文件头第三个 xfail pin 专管
        line = f"{tpath}{sep}{num}{sep}{content}"
        parsed = _parse_content_line(line)
        if parsed is None or parsed != (tpath, num, sep, content):
            fails.append((case, repr(line), parsed))
    assert not fails, f"旧式文本形态反例（seed={_SEED + 1}）：{fails[:6]}"


def test_count_line_relativize_noop_for_relative(tmp_path) -> None:
    rng = random.Random(_SEED + 2)
    base = str(tmp_path)
    for _case in range(_CASES):
        cpath = "sub/" + _gen(rng, rng.randint(1, 8)).replace(":", "")
        line = f"{cpath}:{rng.randint(0, 9999)}"
        assert _relativize_count_line(line, base) == line


@pytest.mark.xfail(
    strict=True,
    reason="文本形态 :\\d+: 抢先歧义（容器上下文行）——字符串手术恒等式保文本、"
    "排序键取错；修法待拍（容器回退改发 NUL 等），修好即 XPASS 提醒摘牌",
)
def test_dash_context_line_with_colon_digits_content_prefers_colon_form() -> None:
    line = r"src/log.py-12-time: 12:30:00 ERROR login failed"
    parsed = _parse_content_line(line)
    assert parsed == ("src/log.py", 12, "-", "time: 12:30:00 ERROR login failed"), parsed


def test_aliasing_boundary_is_the_real_cause() -> None:
    """方向控制：别名序列存在时确实解析不到真实字段（区分度自证）。"""
    line = "sub/dir-7-data.txt\0" + "12:hello"
    parsed = _parse_content_line(line)
    assert parsed == ("sub/dir-7-data.txt", 12, ":", "hello")  # NUL 形态免疫
    text_line = "sub/dir-7-data.txt-12-hello"
    assert _parse_content_line(text_line) != ("sub/dir-7-data.txt", 12, "-", "hello")
