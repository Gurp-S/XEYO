"""Skill 工具不许把"装着但读不出"说成"没装 / 作者禁止调用"。

三处假事实（同一函数里，逐条实测）：
1. SKILL.md 坏 frontmatter / 非法 UTF-8 ⇒ 发现表把条目置 ``broken=True`` 并写好
   ``reason``，但 ``_model_invocable_ok`` 对 broken 返回 False，于是模型收到
   ``Skill X not available for model invocation (model_invocable:false).``
   ——把"读不出"说成"作者关掉了调用"。模型据此不会去修文件，只会放弃或重装。
2. 走到正文读取那一步失败时更直白：``Skill not found: X (broken?).``——
   而第 254 行刚刚确认过这个条目**存在**。
3. ``load_skill_body`` 用 ``read_text(encoding="utf-8")``（严格解码）：发现表有 3s TTL，
   缓存期内用户改了/删了文件，非法字节会让 UnicodeDecodeError **一路逃出工具**
   （registry 对 BaseException 只记不吞）⇒ 整回合被打死。

判据走生产派发（build_default_registry + ToolRegistry.run），对照项也必须成立：
真没装的技能照旧报 not found 并附 Available 列表。
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.catalog import build_default_registry


def _skill(cwd: Path, name: str, body: bytes) -> Path:
    """按 workspace 技能的真实布局落盘，并打开扩展层（与 tests/test_skills_api.py 同源）。"""
    d = cwd / ".xeyo" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_bytes(body)
    settings = cwd / ".xeyo" / "settings.json"
    if not settings.exists():
        settings.write_text(
            json.dumps({"enabled_extensions": True}), encoding="utf-8"
        )
    return d


VALID = b"---\nname: ok-skill\ndescription: fine\n---\n\nDo the thing.\n"
BAD_UTF8 = b"---\nname: bad-skill\ndescription: fine\n---\n\n\xff\xfe not utf8\n"


async def _invoke(reg, name: str):
    return await reg.run(
        ToolUse(id="t", name="Skill", input={"name": name}), AbortController(), skip_ask=True
    )


async def test_broken_skill_is_not_reported_as_invocable_disabled(tmp_path: Path) -> None:
    """缺陷 1：坏 manifest 的条目必须说"读不出 + 原因"，不许说 model_invocable:false。"""
    _skill(tmp_path, "bad-skill", BAD_UTF8)
    reg = build_default_registry(cwd=str(tmp_path))
    res = await _invoke(reg, "bad-skill")
    text = str(res.content)
    assert res.is_error, text[:160]
    assert "model_invocable" not in text, f"把读不出说成作者禁用：{text[:200]!r}"
    assert "not found" not in text.lower(), f"把读不出说成没装：{text[:200]!r}"
    assert "unreadable" in text, text[:200]


async def test_deleted_between_discovery_and_load_is_not_not_found(tmp_path: Path) -> None:
    """缺陷 2：发现表缓存期内文件被删 ⇒ 要说"装着但读不出"，不许说 not found。"""
    path = _skill(tmp_path, "ok-skill", VALID)
    reg = build_default_registry(cwd=str(tmp_path))
    ok = await _invoke(reg, "ok-skill")
    assert not ok.is_error, str(ok.content)[:160]  # 先坐实"装得上、读得出"
    (path / "SKILL.md").unlink()               # 缓存期内的竞态：用户把文件删了
    res = await _invoke(reg, "ok-skill")
    text = str(res.content)
    assert res.is_error, text[:160]
    assert "not found" not in text.lower(), f"存在却被说成没装：{text[:200]!r}"
    assert "could not be read" in text, text[:200]


async def test_encoding_flip_between_discovery_and_load_does_not_kill_the_turn(
    tmp_path: Path,
) -> None:
    """缺陷 3：缓存期内换成非法字节 ⇒ 异常不得逃出工具（逃出=回合被打死）。"""
    path = _skill(tmp_path, "ok-skill", VALID)
    reg = build_default_registry(cwd=str(tmp_path))
    ok = await _invoke(reg, "ok-skill")
    assert not ok.is_error, str(ok.content)[:160]
    (path / "SKILL.md").write_bytes(BAD_UTF8)
    res = await _invoke(reg, "ok-skill")  # 旧实现：这里直接抛 UnicodeDecodeError
    assert isinstance(getattr(res, "content", None), str)


async def test_genuinely_absent_skill_still_says_not_found(tmp_path: Path) -> None:
    """反向对照：真没装的技能照旧报 not found，并给出 Available 列表。"""
    _skill(tmp_path, "ok-skill", VALID)
    reg = build_default_registry(cwd=str(tmp_path))
    res = await _invoke(reg, "no-such-skill")
    text = str(res.content)
    assert res.is_error
    assert "Skill not found: no-such-skill" in text, text[:200]
    assert "ok-skill" in text, f"Available 列表丢了：{text[:200]}"
