"""`job_output.wait` 用裸 `bool()` 解析 ⇒ 模型说"不等"，工具却去等。

实测形状（`tools/job_tools.py:113`）：``wait = bool(input.get("wait"))``。
`wait` 在 schema 里声明成 boolean，但模型经常把它写成字符串（``"false"`` / ``"0"`` /
``"no"`` / ``"off"``），裸 `bool()` 对这些**非空字符串一律给 True** ⇒ 进入
`while wait and status == "running"` 的等待循环，一直耗到 `timeout_ms`
（缺省 30 000ms，上限 600 000ms）。也就是说这一枪做了与要求相反的事，
还把整回合按住最多 30 秒（模型不发第二个 tool call 之前什么都做不了）。

同仓其它四个工具（Bash / Edit / Grep / TodoWrite）都有 `_coerce_bool`
按字面量认 "true/false/1/0/yes/no/on/off"，认不出的回到默认值 —— 这一处是 outlier。

判据走生产派发（build_default_registry + ToolRegistry.run），并在
`get_job_registry` 这个真实接缝上放一个假 registry：它记录 `wait_for_change`
到底有没有被调用。用"有没有调用"判定，而不是拿墙钟差判定（本机 monotonic
粒度 15.625ms，且门在并发跑，计时断言会偶发红）。
"""

from __future__ import annotations

import pytest

import server.job_registry as jr
from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.catalog import build_default_registry


class _FakeRegistry:
    """只实现 job_output 用到的三个方法，并记录等待有没有真的发生。"""

    def __init__(self) -> None:
        self.waited = 0
        self.reads = 0

    def change_token(self, job_id: str, caller: str) -> int:
        return 1

    def read(self, job_id: str, caller: str):
        self.reads += 1
        return ("still running…", 7, "running", False)   # 永远 running，逼出等待分支

    async def wait_for_change(self, job_id: str, caller: str, token: int, *, timeout_s: float):
        self.waited += 1
        return token


@pytest.fixture()
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> _FakeRegistry:
    reg = _FakeRegistry()
    monkeypatch.setattr(jr, "get_job_registry", lambda: reg, raising=True)
    # docker 分支不参与：让它返回空表，控制流落到 registry 分支
    from tools.bash_tool import bash_tool as bt

    monkeypatch.setattr(bt, "docker_bg_snapshot", lambda: [], raising=True)
    return reg


async def _call(tmp_path, payload: dict) -> object:
    reg = build_default_registry(cwd=str(tmp_path))
    return await reg.run(
        ToolUse(id="t", name="job_output", input=payload), AbortController(), skip_ask=True
    )


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "", None, [], ["x"], {"k": 1}])
async def test_falsy_shapes_do_not_enter_the_wait(tmp_path, fake_registry, value) -> None:
    """缺陷回归：这些写法都不许进等待循环（旧实现里 "false"/"0"/"no"/"off"/`["x"]` 全会）。"""
    payload = {"job_id": "j1", "timeout_ms": 1000}
    if value is not None:
        payload["wait"] = value
    res = await _call(tmp_path, payload)
    assert not res.is_error, str(res.content)[:160]
    assert fake_registry.waited == 0, (
        f"wait={value!r} 却被当成 True，进了等待循环（调用 {fake_registry.waited} 次）"
    )


@pytest.mark.parametrize("value", [True, "true", "1", "yes", "on", 1])
async def test_truthy_shapes_still_wait(tmp_path, fake_registry, value) -> None:
    """反向控制：明确要等的写法一个都不许被关小（否则后台任务取证会拿不到输出）。"""
    res = await _call(
        tmp_path, {"job_id": "j1", "wait": value, "timeout_ms": 1000}
    )
    assert not res.is_error, str(res.content)[:160]
    assert fake_registry.waited >= 1, f"wait={value!r} 没进等待循环"


async def test_missing_wait_key_defaults_to_no_wait(tmp_path, fake_registry) -> None:
    """缺省口径不变：不给 wait 就是不等。"""
    res = await _call(tmp_path, {"job_id": "j1", "timeout_ms": 1000})
    assert not res.is_error, str(res.content)[:160]
    assert fake_registry.waited == 0


async def test_unknown_wait_word_is_not_silently_true(tmp_path, fake_registry) -> None:
    """认不出的字面量回到默认值（不等），与同仓 _coerce_bool 口径一致。"""
    res = await _call(tmp_path, {"job_id": "j1", "wait": "maybe", "timeout_ms": 1000})
    assert not res.is_error, str(res.content)[:160]
    assert fake_registry.waited == 0
