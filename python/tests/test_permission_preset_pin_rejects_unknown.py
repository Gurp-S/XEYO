"""权限 preset：会话**首建 pin** 这一路不许把打错的字静默放宽成 workspace-write。

同一字段两条路：
- 运行时切档 `POST /v1/sessions/{sid}/runtime-preset` → `RuntimePresetStore.set`
  用原始名校验，未知值返回 None ⇒ 路由报 422。它的 docstring 明写
  「presets.normalize_preset 会把未知值回退为默认（workspace-write），
  这里必须用原始名校验 —— **用户打字错误不能静默变成"工作区写"**」。
- 首建 pin（`SessionPool.get_or_create(permission_preset=…)`）原先直接调
  `normalize_preset` ⇒ 正好绕过自己立的那条红线：只读意图 + 一个字母的错
  = 拿到写权限，而且一声不响。

修法只补校验：认不出的**非空**值 → `ValueError`（`server/routers/chat.py:170` 既有
`except (FileNotFoundError, NotADirectoryError, ValueError)` ⇒ 干净 400，不必改在途文件）；
空 / 缺省仍回退默认档（现状不变）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from permissions.presets import DEFAULT_PRESET, PERMISSION_PRESETS, normalize_preset  # noqa: E402
from permissions.runtime_preset import RuntimePresetStore  # noqa: E402
from server.session_pool import ModelConfig, SessionPool  # noqa: E402

VALID = tuple(sorted(PERMISSION_PRESETS))
TYPOS = ("read_only", "read-only", "readir", "ful", "wrok-space-write", "WORKSPACE WRITE", "none")


def _cfg() -> ModelConfig:
    return ModelConfig(
        provider="deepseek", api_key="k", base_url="http://127.0.0.1:1", model="m"
    )


def test_control_valid_names_pin_themselves() -> None:
    """正向自证：三个合法值原样 pin（本修法不许改变它们）。"""
    for name in VALID:
        assert normalize_preset(name) == name, name


def test_control_absent_or_empty_keeps_current_default() -> None:
    """缺省 / 空值现状不变——本 bug 的范围只到"给了但认不出"。"""
    for value in (None, "", "   "):
        assert normalize_preset(value) == DEFAULT_PRESET, value


def test_runtime_store_already_rejects_the_same_typos() -> None:
    """两端一致性：运行时切档那一路早就拒了（本修法只是把首建对齐过去）。"""
    store = RuntimePresetStore()
    for value in TYPOS:
        assert store.set("s-typo", value) is None, value
        assert store.live("s-typo") is None, value


@pytest.mark.parametrize("typo", TYPOS)
def test_first_pin_rejects_unknown_preset_instead_of_widening(tmp_path: Path, typo: str) -> None:
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    sid = "s-typo-1"
    with pytest.raises(ValueError):
        pool.get_or_create(sid, _cfg(), cwd=str(tmp_path), permission_preset=typo)
    # 被拒之后不得留下"已 pin 成 workspace-write"的档案（否则下一次复用就中招）
    assert pool._profiles.get(sid) is None, pool._profiles


def test_valid_readonly_still_pins_after_a_rejected_request(tmp_path: Path) -> None:
    """反向自证：合法 readonly 照旧建会话；被拒的会话号可复用，没被写脏。"""
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    sid = "s-reuse"
    with pytest.raises(ValueError):
        pool.get_or_create(sid, _cfg(), cwd=str(tmp_path), permission_preset="read_only")
    eng = pool.get_or_create(sid, _cfg(), cwd=str(tmp_path), permission_preset="readonly")
    assert eng.permission_profile == "readonly", eng.permission_profile
    assert pool._profiles.get(sid) == "readonly", pool._profiles


def test_empty_preset_still_creates_with_default(tmp_path: Path) -> None:
    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    eng = pool.get_or_create("s-blank", _cfg(), cwd=str(tmp_path), permission_preset="  ")
    assert eng.permission_profile == DEFAULT_PRESET, eng.permission_profile
