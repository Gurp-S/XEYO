"""技能直呼宿主注入（engine/skill_preinvoke）测试。

覆盖：手势词边界、命令命名空间优先、user_invocable 门控、$ARGUMENTS 语义、
开关回退。注入装配点本身由 tests/test_t_now_block_registry.py 执法。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.skill_preinvoke import (
	_leading_slash_token,
	preinvoke_enabled,
	preinvoke_skill_block,
)


# ---------------------------------------------------------------- 手势词边界

def test_leading_token_basic():
	assert _leading_slash_token("/commit fix bug") == ("commit", "fix bug")
	assert _leading_slash_token("/review") == ("review", "")
	assert _leading_slash_token("/review\n请全量审查") == ("review", "请全量审查")
	assert _leading_slash_token("  /plan  先规划") == ("plan", "先规划")


def test_leading_token_word_boundary():
	# 路径不命中（token 后跟 / 或非空白）
	assert _leading_slash_token("/nfs-hg/xxx 看看这个") is None
	# 首个非空行不是 / 开头 → 非手势
	assert _leading_slash_token("帮我 /review 一下") is None
	assert _leading_slash_token("普通消息") is None
	assert _leading_slash_token("") is None
	# 空token（ lone / ）不算
	assert _leading_slash_token("/ 只是斜杠") is None


# ---------------------------------------------------------------- 命令优先

def test_slash_command_namespace_wins(tmp_path: Path):
	# help 是 slash registry 命令 → 绝不当作技能手势（即便存在同名技能）
	block = preinvoke_skill_block(str(tmp_path), "/help 我")
	assert block == ""
	# 中文别名同判
	assert preinvoke_skill_block(str(tmp_path), "/目标 x") == ""


# ---------------------------------------------------------------- 注入主路径

def _make_skill(tmp_path: Path, name: str = "review", *, body: str = "步骤一",
				user_invocable: bool = True, broken: bool = False):
	from extension.skill_loader import SkillEntry

	skill_dir = tmp_path / name
	skill_dir.mkdir(exist_ok=True)
	(skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
	return SkillEntry(
		name=name,
		path=skill_dir,
		source="workspace",
		description="审查技能",
		user_invocable=user_invocable,
		broken=broken,
	)


@pytest.fixture()
def fake_skills(monkeypatch):
	def install(*entries):
		import tools.skill_tool.skill_tool as st

		monkeypatch.setattr(st, "_skill_entries_with_descriptions", lambda cwd: list(entries))
		return st

	return install


def test_preinvoke_injects_body(fake_skills, tmp_path: Path):
	entry = _make_skill(tmp_path, body="1. 先读 diff\n2. 出报告")
	st = fake_skills(entry)
	block = preinvoke_skill_block(str(tmp_path), "/review 全量审查")
	assert "Skill invocation" in block
	assert "<skill_content>" in block and "</skill_content>" in block
	assert "1. 先读 diff" in block
	assert "/review 直接调用" in block
	# 不再要求模型自己去调 Skill 工具
	assert "不要" in block and "Skill 工具" in block
	_ = st


def test_preinvoke_arguments_semantics(fake_skills, tmp_path: Path):
	entry = _make_skill(tmp_path, body="对 $ARGUMENTS 执行审查")
	fake_skills(entry)
	block = preinvoke_skill_block(str(tmp_path), "/review login.py")
	assert "对 login.py 执行审查" in block
	# 无 $ARGUMENTS 占位 → 追加「调用参数」节
	entry2 = _make_skill(tmp_path, name="plain", body="步骤")
	fake_skills(entry2)
	block2 = preinvoke_skill_block(str(tmp_path), "/plain 附加参数")
	assert "## 调用参数" in block2 and "附加参数" in block2


def test_preinvoke_gates(fake_skills, tmp_path: Path):
	# user_invocable:false → 不注入（模型侧目录技能走 Skill 工具）
	fake_skills(_make_skill(tmp_path, user_invocable=False))
	assert preinvoke_skill_block(str(tmp_path), "/review x") == ""
	# broken → 不注入
	fake_skills(_make_skill(tmp_path, broken=True))
	assert preinvoke_skill_block(str(tmp_path), "/review x") == ""
	# 查无此名 → 普通散文
	fake_skills()
	assert preinvoke_skill_block(str(tmp_path), "/nope x") == ""
	# 非手势文本 → 空
	assert preinvoke_skill_block(str(tmp_path), "普通任务") == ""


def test_preinvoke_body_truncated(fake_skills, tmp_path: Path, monkeypatch):
	import engine.skill_preinvoke as sp

	entry = _make_skill(tmp_path, body="x" * (sp.BODY_MAX + 100))
	fake_skills(entry)
	block = preinvoke_skill_block(str(tmp_path), "/review x")
	assert len(block) < sp.BODY_MAX + 500
	assert "已截断" in block


# ---------------------------------------------------------------- 开关

def test_flag_toggle(monkeypatch):
	monkeypatch.delenv("XEYO_SKILL_PREINVOKE", raising=False)
	assert preinvoke_enabled() is True
	monkeypatch.setenv("XEYO_SKILL_PREINVOKE", "off")
	assert preinvoke_enabled() is False
	monkeypatch.setenv("XEYO_SKILL_PREINVOKE", "0")
	assert preinvoke_enabled() is False
