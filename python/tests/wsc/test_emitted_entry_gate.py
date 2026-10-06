"""发射面入口周期门的夹具测试（`evals/wsc_emitted_entries`）。

为什么要有这一组：`tests/wsc/test_handle_style.py` 那组绿测的分子分母都取自
**冷层对象**（`proj.cold.handles`），实测**裁卡面不会让任何一条现有测试变红** ——
被裁掉的入口根本不进分母。本门把分母换成"发射文本里引擎声明的入口数"，
于是卡面缩水 ⇒ 分母缩水（被看见），而不是"通过率照旧"。

三态纪律（把不可判的当失败或当通过都是造数）：
- `ok` —— 真 `FileReadTool` 按声明参数执行成功；
- `fail` —— 工具按自己的上限报错（25k token / 2000 行）；
- `undecidable` —— 归档文件已不在 / 越权 ⇒ 不参与通过率。

口径同源：解析用 `synaptic/handles._READ_RE`（生产渲染同一张正则），
判定用真的 `FileReadTool`，本文件不写第二套上限数字。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.wsc_emitted_entries import (
    FAIL,
    UNDECIDABLE,
    census,
    declarations,
    engine_declarations,
)

#: 生产上限（从被量的工具本身取，不在本文件里抄一份）
from tools.file_read_tool.file_read_tool import DEFAULT_MAX_TOKENS, MAX_LINES_TO_READ

_LINE = "z" * 60


def _archive(lines: int) -> str:
    return "\n".join(f"{i:04d}-{_LINE}" for i in range(1, lines + 1))


def _read_call(path: str, offset: int, limit: int) -> str:
    return f"Read(file_path='{path}', offset={offset}, limit={limit})"


@pytest.fixture()
def world(tmp_path):
    """一份真实归档 + 一个 `*.working.json`（`last_x_sent` 按生产形态存成 JSON 串）。"""
    offload = tmp_path / ".xeyo_offload" / "wsc"
    offload.mkdir(parents=True)
    view = offload / "cold.txt"
    view.write_text(_archive(MAX_LINES_TO_READ + 500), encoding="utf-8")
    return tmp_path, view


def _working(workspace: Path, view: Path, emitted: str) -> Path:
    sdir = workspace / "sessions"
    sdir.mkdir(exist_ok=True)
    msgs = [{"role": "user", "content": emitted}]
    (sdir / "s_gate.working.json").write_text(
        json.dumps({"session_id": "s_gate", "last_x_sent": json.dumps(msgs, ensure_ascii=False)},
                   ensure_ascii=False), encoding="utf-8")
    return sdir


def _rel(view: Path, workspace: Path) -> str:
    return view.relative_to(workspace).as_posix()


def test_three_states_are_counted_separately(world) -> None:
    """一条可执行 / 一条超行数 / 一条缺文件 ⇒ ok=1 fail=1 undecidable=1，各归各的账。"""
    workspace, view = world
    rel = _rel(view, workspace)
    emitted = "\n".join([
        _read_call(rel, 1, 5),                                     # 能执行
        _read_call(rel, 1, MAX_LINES_TO_READ + 10),               # 超 2000 行 ⇒ 工具抛错
        _read_call(".xeyo_offload/wsc/gone.txt", 1, 5),           # 归档已不在 ⇒ 不可判
    ])
    rep = census(_working(workspace, view, emitted), workspace)
    row = rep["rows"][0]
    assert row["declared"] == 3
    assert (row["ok"], row["fail"], row["undecidable"]) == (1, 1, 1), row
    assert row["kinds"]["over_cap"] == 1 and row["kinds"]["missing"] == 1
    assert rep["fail_rate"] == pytest.approx(1 / 2), "通过率的分母只能是可判样本"


def test_token_cap_is_caught_by_the_tool_not_by_arithmetic(world) -> None:
    """行数没超、但一次取回超 25k token ⇒ 判失败，且失败文本来自工具自己的措辞。"""
    workspace, view = world
    rel = _rel(view, workspace)
    limit = MAX_LINES_TO_READ                      # 2000 行：不触发行数闸
    need = limit * (len(_LINE) + 5)                # 约 13 万字符 ⇒ 约 3.3 万 token
    assert need // 4 > DEFAULT_MAX_TOKENS, f"夹具造不出超 token 的情况：{need // 4}"
    emitted = _read_call(rel, 1, limit)
    rep = census(_working(workspace, view, emitted), workspace)
    row = rep["rows"][0]
    assert (row["ok"], row["fail"]) == (0, 1), row
    assert row["kinds"] == {"over_cap": 1}
    assert rep["judged_total"] == 1 and rep["fail_rate"] == 1.0


def test_missing_is_not_a_failure_when_the_probe_cannot_judge(world) -> None:
    """缺归档 ⇒ 不可判；同一份文本按"缺即失败"的夹具口径跑时才算失败。

    两档都得能出数，是因为现网普查与自造夹具问的不是一个问题。
    """
    workspace, view = world
    emitted = _read_call(".xeyo_offload/wsc/gone.txt", 1, 5)
    rep = census(_working(workspace, view, emitted), workspace)
    assert rep["judged_total"] == 0 and rep["fail_rate"] is None, "不可判不许出率"
    assert rep["undecidable_total"] == 1
    direct = declarations(emitted)
    from evals.wsc_emitted_entries import judge

    v = judge(direct, read=lambda a: (True, "file does not exist"), missing_policy=FAIL)
    assert (v.fail, v.undecidable) == (1, 0)
    v2 = judge(direct, read=lambda a: (True, "file does not exist"),
               missing_policy=UNDECIDABLE)
    assert (v2.fail, v2.undecidable) == (0, 1)


def test_tool_output_mentions_are_not_engine_declarations(world) -> None:
    """工具结果正文里的 `Read(...)`（测试源码、日志）不算引擎声明的出口。

    现网实测：某会话 15 条"声明"里 12 条是被 `<tool_output>` 裹着的断言行 ——
    混进分母就是拿别人的字符串给自己判分。
    """
    workspace, view = world
    rel = _rel(view, workspace)
    emitted = (
        _read_call(rel, 1, 5) + "\n"
        + "<tool_output tool=Read>\n"
        + '   243\tassert hr.expression("node://7") == ' + _read_call("v.txt", 4, 3) + "\n"
        + "</tool_output>\n"
    )
    assert len(declarations(emitted)) == 2
    eng = engine_declarations(emitted)
    assert [d.path for d in eng] == [rel], eng


def test_cutting_the_card_face_shrinks_the_denominator(world) -> None:
    """这条是本门的全部意义：卡面入口被裁光 ⇒ **分母变 0、率报不出来**，
    而不是"通过率照旧 100%"。（另测过：同样改动下 `test_handle_style.py` 全绿，
    因为它的分子分母都取自冷层对象——见 docs 第 23 条与 §15.17 的记录。）"""
    workspace, view = world
    rel = _rel(view, workspace)
    full = "\n".join(_read_call(rel, off, 5) for off in (1, 11, 21, 31))
    rep_full = census(_working(workspace, view, full), workspace)
    assert rep_full["declared_total"] == 4
    assert rep_full["judged_total"] == 4

    cut = census(_working(workspace, view, "[PRUNED] 4 cards, entries removed"), workspace)
    assert cut["sessions_with_entries"] == 0
    assert cut["declared_total"] == 0 and cut["judged_total"] == 0
    assert cut["fail_rate"] is None, "分母为空时不许报数（那是假绿）"


def test_flatten_parses_the_json_string_container(world) -> None:
    """`last_x_sent` 是 JSON 串：不 parse 就匹配 ⇒ 会被转义打断而虚报缺失（踩过）。"""
    workspace, view = world
    rel = _rel(view, workspace)
    emitted = _read_call(rel, 1, 5)
    sdir = _working(workspace, view, emitted)
    raw = json.loads((sdir / "s_gate.working.json").read_text(encoding="utf-8"))
    assert isinstance(raw["last_x_sent"], str), "夹具没按生产形态存成 JSON 串"
    rep = census(sdir, workspace)
    assert rep["declared_total"] == 1
