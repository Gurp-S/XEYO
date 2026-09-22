"""记忆系统开关：设置持久化 + 运行时 os.environ 桥接 + /v1/settings/memory 端点。

运行：``py -3.11 -m pytest tests/test_memory_switches.py -q``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memory.memory_switches import (
	MEMORY_SWITCHES,
	apply_to_environ,
	current,
	save,
)
from server.app import app

_LAN = ("203.0.113.9", 55555)


def _ws(tmp_path: Path) -> Path:
	ws = tmp_path / "ws"
	(ws / ".xeyo").mkdir(parents=True, exist_ok=True)
	return ws


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
	"""隔离 XEYO_HOME / XEYO_CWD：settings 只看 tmp，绝不读开发者真实配置。

	``_memory_store`` 会合并 home + workspace 两处 settings.json；不隔离的话，本机
	``~/.xeyo/settings.json`` 的残留键会污染 stale/prune 断言。
	"""
	home = tmp_path / "home"
	home.mkdir(exist_ok=True)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.delenv("XEYO_CWD", raising=False)
	return home


# ---- 模块层 ----
def test_defaults_when_unset(monkeypatch) -> None:
	for key, *_ in MEMORY_SWITCHES:
		monkeypatch.delenv(key, raising=False)
	cur = current(None)
	# 2026-09-06 用户决策「v61 默认开启」。原先这里断言的是 "project"，与紧邻下一行
	# 注释、以及 `l5_flag.DEFAULT_MODE` 互相矛盾（那三个陈诉都对，只有断言是错的）。
	assert cur["XEYO_L5"]["value"] == "v61"
	# 2026-09-06 固化：C2_GATE / V61_PARETO/SI/DYNAMIC_R / Path A 三公式已删除（v61 默认开启后冗余）
	assert "XEYO_C2_GATE" not in cur
	assert "XEYO_V61_PARETO" not in cur
	assert cur["XEYO_TOOL_AGING"]["value"] == "0"


def test_l5_has_exactly_one_default_authority(monkeypatch) -> None:
	"""L5 只能有一个默认源。

	事故形态：``l5_flag.DEFAULT_MODE = "v61"`` 而注册表默认曾写成 ``"project"``，且
	``l5_mode()`` 先问 ``get_value``（返回合法非空的注册表默认）⇒ 那段 v61 兜底
	**永远走不到**。读代码的人以为默认是 v61、运行时却是 project，于是消融实验在
	"我以为开着 v61"的前提下跑出 project 的数字。
	"""
	from memory.l5_flag import DEFAULT_MODE, l5_mode

	monkeypatch.delenv("XEYO_L5", raising=False)
	assert l5_mode() == DEFAULT_MODE, "l5_flag 的兜底与注册表默认分叉了"


def test_env_ignored_when_settings_absent(monkeypatch) -> None:
	"""环境变量不再参与：即使设置了合法值，settings 缺省也落默认（彻底禁 env）。"""
	for key, *_ in MEMORY_SWITCHES:
		monkeypatch.delenv(key, raising=False)
	monkeypatch.setenv("XEYO_C2_GATE", "0")
	cur = current(None)
	assert "XEYO_C2_GATE" not in cur  # 已删键：env / settings 均不生效（固化恒 True）


def test_save_and_settings_win(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	save({"XEYO_TOOL_AGING": True}, cwd=str(ws))
	data = json.loads((ws / ".xeyo" / "settings.json").read_text(encoding="utf-8"))
	assert data["memory"]["XEYO_TOOL_AGING"] == "1"
	cur = current(str(ws))
	assert cur["XEYO_TOOL_AGING"]["value"] == "1"
	assert cur["XEYO_TOOL_AGING"]["source"] == "settings"


def test_apply_to_environ_sets_runtime_env(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	save({"XEYO_TOOL_AGING": "1"}, cwd=str(ws))
	ws2 = _ws(tmp_path / "other")
	applied = apply_to_environ(str(ws))
	assert applied.get("XEYO_TOOL_AGING") == "1"


def test_reject_illegal_value(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with pytest.raises(ValueError):
		save({"XEYO_L5": "bogus"}, cwd=str(ws))


# ---- API 层 ----
def test_memory_get(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with TestClient(app) as c:
		r = c.get(f"/v1/settings/memory?workspace={ws}")
		assert r.status_code == 200, r.text
		body = r.json()
	assert body["ok"] is True
	assert body["switches"]["XEYO_TOOL_AGING"]["value"] in ("0", "1")


def test_memory_post_saves_and_applies(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with TestClient(app) as c:
		r = c.post(
			f"/v1/settings/memory?workspace={ws}",
			json={"updates": {"XEYO_TOOL_AGING": True}},
		)
		assert r.status_code == 200, r.text
		body = r.json()
	assert body["ok"] is True
	assert body["memory"]["XEYO_TOOL_AGING"] == "1"
	assert body["switches"]["XEYO_TOOL_AGING"]["value"] == "1"


def test_memory_post_unknown_switch(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with TestClient(app) as c:
		r = c.post(
			f"/v1/settings/memory?workspace={ws}",
			json={"updates": {"XEYO_NOPE": "1"}},
		)
		assert r.status_code == 200
		body = r.json()
	assert body["ok"] is False


def test_memory_rejected_from_lan() -> None:
	with TestClient(app, client=_LAN) as c:
		assert c.get("/v1/settings/memory").status_code == 403
		assert c.post("/v1/settings/memory", json={}).status_code == 403
		assert c.post("/v1/settings/memory/snapshot").status_code == 403
		assert c.get("/v1/settings/memory/report").status_code == 403
		assert c.get("/v1/settings/memory/report/view").status_code == 403


def test_memory_report_view_serves_html(monkeypatch, tmp_path: Path) -> None:
	"""「打开报告」的 http 入口：有报告 = text/html 可直接渲染；没报告 = 404（不 500）。

	桌面壳的 shell:allow-open 只放行 http(s)（file:// 被其 scope 正则拒绝），
	故按钮走这个只读入口，而不是 file://。
	"""
	import scripts.memory_stack_eval as M

	report = tmp_path / "A3-monitor.html"
	monkeypatch.setattr(M, "A3_HTML", report)

	with TestClient(app) as c:
		assert c.get("/v1/settings/memory/report/view").status_code == 404
		report.write_text("<!doctype html><title>A3-monitor</title><p>ok</p>", encoding="utf-8")
		r = c.get("/v1/settings/memory/report/view")

	assert r.status_code == 200, r.text
	assert r.headers["content-type"].startswith("text/html")
	assert "A3-monitor" in r.text
	assert r.headers.get("cache-control") == "no-store"


def test_memory_report_info_shape(monkeypatch, tmp_path: Path) -> None:
	"""设置页「打开报告」的元信息：报告在/不在都返回确定形状（不 500）；路径取生成器常量。"""
	import scripts.memory_stack_eval as M

	report = tmp_path / "A3-monitor.html"
	monkeypatch.setattr(M, "A3_HTML", report)

	with TestClient(app) as c:
		missing = c.get("/v1/settings/memory/report")
		assert missing.status_code == 200, missing.text
		body = missing.json()
		assert body["ok"] is False and body["exists"] is False
		assert body["path"] == str(report)

		report.write_text(
			# 前缀 >4KB 的样式块：真实报告前 16KB 是 CSS，payload 在后面；
			# 只扫头部会取不到 generated_at（曾漏，故这里固定按真实形态构造）。
			'<!doctype html><style>'
			+ ('.a{color:#123456}'
				* 400)
			+ '</style><script>window.__A3__={"generated_at": "2026-09-17T04:39:52.912519+00:00",'
			' "days": [{"day": "2026-09-16", "total": {"day": "2026-09-16", "requests": 1}}]}</script>',
			encoding="utf-8",
		)
		found = c.get("/v1/settings/memory/report").json()

	assert found["ok"] is True and found["exists"] is True
	assert found["bytes"] == report.stat().st_size
	assert found["generated_at"] == "2026-09-17T04:39:52.912519+00:00"
	# 同一天在 payload 里出现两次（day 行 + total.detail）也只算一天
	assert found["days"] == ["2026-09-16"]
	assert found["url"].startswith("file://")


# ---- GUI 暴露面与「显示 == 生效」契约 ----
def test_only_c2_llm_summary_is_gui_exposed() -> None:
	"""产品面板只暴露 C2 摘要 LLM 旁路；其余是测试/评测便捷开关，仅后端可切。"""
	cur = current(None)
	exposed = {k for k, v in cur.items() if v["exposed"]}
	assert exposed == {"XEYO_C2_LLM_SUMMARY"}


def test_dead_switch_reports_ignored_and_effective_default(tmp_path: Path) -> None:
	"""恒关占位键（XEYO_MEMORY_INDEX_LIVE）：settings 写 1 也必须报 ignored + effective=0。

	红线：GUI 按 effective 显示，禁止出现「显示开、实际关」（历史缺陷）。
	"""
	ws = _ws(tmp_path)
	# 直接落盘（走 save 会被注册表语义接受，但运行时本就不读该键）
	save({"XEYO_MEMORY_INDEX_LIVE": "1"}, cwd=str(ws))
	cur = current(str(ws))
	item = cur["XEYO_MEMORY_INDEX_LIVE"]
	assert item["value"] == "1"  # settings 里的字面值确实被记下了
	assert item["ignored"] is True
	assert item["effective"] == "0"  # 运行时真值 = 默认
	assert item["source"] == "ignored"  # 不再谎报 "settings"
	assert item["exposed"] is False


def test_live_switch_reports_effective_equal_value(tmp_path: Path) -> None:
	"""真正被运行时读取的开关：effective == value，source 随 settings/default。"""
	ws = _ws(tmp_path)
	save({"XEYO_C2_LLM_SUMMARY": "1"}, cwd=str(ws))
	item = current(str(ws))["XEYO_C2_LLM_SUMMARY"]
	assert item["ignored"] is False
	assert item["effective"] == "1"
	assert item["source"] == "settings"

	# settings 未指定 → 默认，仍是 effective == value
	ws2 = _ws(tmp_path / "other")
	item2 = current(str(ws2))["XEYO_C2_LLM_SUMMARY"]
	assert item2["effective"] == "0"
	assert item2["source"] == "default"


# ---- 残留键清理（缺陷②）----
_STALE = {
	"XEYO_MEMORY_RERANK_PREFERENCE": "1",
	"XEYO_MEMORY_SQLITE_INDEX": "1",
	"XEYO_CACHE_COOLDOWN_OMEGA": "1",
	"XEYO_C2_GATE": "1",
}


def _write_settings_with_stale(ws: Path, extra: dict | None = None) -> Path:
	path = ws / ".xeyo" / "settings.json"
	data = {"enabled_extensions": True, "memory": dict(_STALE, **({"XEYO_L5": "v61"} if extra is None else extra))}
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
	return path


def test_stale_keys_is_readonly(tmp_path: Path) -> None:
	from memory.memory_switches import stale_keys

	ws = _ws(tmp_path)
	path = _write_settings_with_stale(ws)
	before = path.read_text(encoding="utf-8")
	assert stale_keys(str(ws)) == sorted(_STALE)
	assert path.read_text(encoding="utf-8") == before  # 只读：不写盘


def test_prune_stale_removes_only_stale_and_keeps_valid(tmp_path: Path) -> None:
	from memory.memory_switches import prune_stale, stale_keys

	ws = _ws(tmp_path)
	path = _write_settings_with_stale(ws)
	removed = prune_stale(str(ws))
	assert removed == sorted(_STALE)
	data = json.loads(path.read_text(encoding="utf-8"))
	assert data["memory"] == {"XEYO_L5": "v61"}  # 有效键保留
	assert data["enabled_extensions"] is True  # 其他段不碰
	assert stale_keys(str(ws)) == []
	# 无残留时零写入：内容逐字节不变
	before = path.read_text(encoding="utf-8")
	assert prune_stale(str(ws)) == []
	assert path.read_text(encoding="utf-8") == before


def test_save_prunes_stale_keys(tmp_path: Path) -> None:
	"""保存任一开关时顺带清掉残留键（GUI「立即清理」= POST 空 updates）。"""
	ws = _ws(tmp_path)
	path = _write_settings_with_stale(ws)
	save({"XEYO_C2_LLM_SUMMARY": "1"}, cwd=str(ws))
	data = json.loads(path.read_text(encoding="utf-8"))
	assert set(data["memory"]) == {"XEYO_C2_LLM_SUMMARY", "XEYO_L5"}


def test_api_reports_stale_and_prunes_on_post(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	_write_settings_with_stale(ws)
	with TestClient(app) as c:
		r = c.get(f"/v1/settings/memory?workspace={ws}")
		assert r.status_code == 200, r.text
		get_body = r.json()
		assert get_body["ok"] is True
		assert sorted(get_body["stale"]) == sorted(_STALE)

		r2 = c.post(f"/v1/settings/memory?workspace={ws}", json={"updates": {}})
		assert r2.status_code == 200, r2.text
		post_body = r2.json()
		assert post_body["ok"] is True
		assert sorted(post_body["pruned"]) == sorted(_STALE)
		assert post_body["stale"] == []
		assert (ws / ".xeyo" / "settings.json").read_text(encoding="utf-8").count("XEYO_C2_GATE") == 0
