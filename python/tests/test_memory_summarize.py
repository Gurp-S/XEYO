"""memory.summarize：C2 摘要“语义片段”按内容类型动态抽取。"""

from __future__ import annotations

from memory.summarize import extract_tool_summary, extract_value_facts, is_error_like
from memory.runtime import deterministic_c2_summary


def _grep_like() -> str:
    return "\n".join(
        f"src/core/engine.py:4{i}:  def run(self):" for i in range(120)
    )


def _traceback() -> str:
    return (
        "Traceback (most recent call last):\n"
        '  File "tests/test_x.py", line 42, in test_thing\n'
        "    assert 1 == 2\n"
        "  File \"src/core/engine.py\", line 12, in run\n"
        "    return _eval(c)\n"
        "AssertionError: expected 2, got 1\n"
    )


# ---------- is_error_like ----------

def test_is_error_like_traceback():
    assert is_error_like(_traceback())


def test_is_error_like_exception_word():
    assert is_error_like("RuntimeError: boom\n  at com.x.Y.run(Y.java:3)")


def test_is_error_like_plain_text_false():
    assert not is_error_like("hello world\nthis is a normal message")


# ---------- extract_tool_summary: grep ----------

def test_grep_summary_keeps_stats_not_raw_head():
    out = extract_tool_summary(_grep_like(), "Grep", max_text=160)
    assert "120 matches" in out
    assert "engine.py" in out
    assert "@line" in out
    # 不再把“前 160 字符”直接贴出来（那样会是几十行 def run(self):）
    assert out.count("def run") < 8
    assert "…" in out or "@line" in out


def test_grep_summary_short_unchanged():
    short = "src/a.py:1: echo hi"
    assert extract_tool_summary(short, "Grep") == short


# ---------- extract_tool_summary: error / 栈回溯 ----------

def test_error_summary_keeps_head_and_tail():
    out = extract_tool_summary(_traceback(), "Bash", max_text=160)
    # 头部栈帧（哪个文件几行）与尾部异常都要在
    assert "tests/test_x.py" in out or "engine.py" in out
    assert "AssertionError" in out
    assert "…" in out  # 中间被折叠


# ---------- extract_tool_summary: 通用长文本 -> head+tail ----------

def test_long_text_head_tail():
    body = "line\n" * 200 + "tail_marker\n"
    out = extract_tool_summary(body, "Bash", max_text=160)
    assert out.startswith("line")
    assert "tail_marker" in out


def test_read_keeps_structure_and_line_count():
    file_body = "import os\n" + "x = 1\n" * 200 + "print(x)\n"
    out = extract_tool_summary(file_body, "Read", max_text=160)
    # 总行数 + 结构签名（import / 顶层赋值）都保留，"文件里有什么"这层不被压丢
    assert "lines" in out
    assert "import os" in out
    assert "print(x)" not in out  # 不保留尾部大段（保头部与结构，而非整文件尾部）


def test_read_code_file_keeps_function_signatures():
    code = "import os\n\n\ndef run():\n    return 1\n\n\ndef process(x):\n    return x * 2\n\n" * 40
    out = extract_tool_summary(code, "Read", max_text=160)
    assert "def run():" in out
    assert "def process(x):" in out
    assert "import os" in out
    assert "lines" in out


def test_read_short_content_verbatim():
    s = "short file content\n"
    assert extract_tool_summary(s, "Read") == s.strip()


# ---------- 取值/定义抽取（read 大文件保留取值） ----------

_PARAM_TABLE = """### 4.7 计算公式 v6.1（实现基线）

| 记号 | 人话 | 默认 |
| --- | --- | --- |
| \\(g\\) | 缓存块 | DeepSeek 64 |
| \\(\\theta\\) | 质量下限 | 0.35 |
| \\(\\alpha_{win}\\) | 软顶占窗口 | 0.55 |
| r_summary | 摘要保真先验 | 0.6 |
| t_k | 尾部条数 | 3 |
"""


def test_extract_value_facts_param_table_skips_header():
    facts = extract_value_facts(_PARAM_TABLE)
    names = {n for n, _v in facts}
    assert "记号" not in names  # 表头行被排除
    assert any(n.startswith("\\") for n in names)  # 符号名如 \\(\\theta\\) 被抽到
    assert ("r_summary", "0.6") in facts or ("r_summary", "0.6") in facts
    assert len(facts) >= 4


def test_read_param_table_keeps_values():
    out = extract_tool_summary(_PARAM_TABLE, "Read", max_text=160)
    assert "params" in out
    assert "0.35" in out
    assert "0.55" in out
    assert "0.6" in out


def test_extract_value_facts_skips_local_vars():
    code = (
        "import os\n"
        "MAX_TOOL_RESULT_CHARS = 16000\n"
        "KEEP_TAIL_MESSAGES = 6\n"
        "def run():\n"
        "    x = 1\n"
        "    y = 2\n"
        "    result = compute(x)\n"
        "    self.cache = {}\n"
        "    return result\n"
    )
    facts = extract_value_facts(code)
    names = {n for n, _v in facts}
    assert "MAX_TOOL_RESULT_CHARS" in names
    assert "x" not in names  # 局部变量被过滤
    assert "self.cache" not in names
    assert "result" not in names


def test_value_not_over_generic_code():
    plain = "def hello(name):\n    return 'hi ' + name\n\n\nprint(hello('world'))\n"
    assert extract_value_facts(plain) == []
    out = extract_tool_summary(plain, "Read", max_text=160)
    assert "params" not in out  # 普通代码不误判为取值摘要


# ---------- 短内容不误伤 ----------

def test_short_content_verbatim():
    s = "short result"
    assert extract_tool_summary(s, "Grep") == s


# ---------- deterministic_c2_summary 端到端 ----------

def _tool_result(uid: str, content: str, *, name: str = "Grep") -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": uid, "content": content, "is_error": False}
        ],
        "name": name,
    }


def _assistant_use(uid: str, name: str) -> dict:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": uid, "name": name, "input": {"q": "x"}}],
    }


def test_c2_summary_uses_type_aware_snippet():
    left = [
        {"role": "user", "content": "find the caller"},
        _assistant_use("g1", "Grep"),
        _tool_result("g1", _grep_like()),
        {"role": "assistant", "content": "done"},
    ]
    out = deterministic_c2_summary(left, style="new")
    # 摘要行里有“多少 matches”统计（类型感知），而不是原始 grep 前 160 字符
    assert "matches" in out
    assert out.count("def run") < 8
    # 无名字的 tool_result 也能靠内容形态兜底 grep
    legacy = deterministic_c2_summary(left, style="legacy")
    assert legacy.count("::") == 0  # legacy 基线不携带片段
    assert "compacted 4 earlier messages" in legacy
