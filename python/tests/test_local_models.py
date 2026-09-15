"""本地模型（llama.cpp）：配置持久化 + 授权位 + 进程管理器 + /v1/local-models 端点。

运行：``py -3.11 -m pytest tests/test_local_models.py -q``

不碰真实 llama-server：进程相关用例只验证"命令怎么拼、失败怎么报、状态长什么样"，
真机起停属于手工验证（见交付说明），不放进单测——那会让 CI 依赖显卡与 8GB 权重。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localmodels import catalog, config, gate
from localmodels.manager import LocalModelManager
from server.app import app

_LAN = ("203.0.113.9", 55555)

#: PID 归属判定靠 ``tasklist`` 的镜像名；非 Windows 下拿不到名字，会退化成
#: "存活即我们"。涉及"外来 pid 不得被杀"的用例必须在 Windows 上跑，否则
#: 那条退化路径会把测试进程自己当成本地模型杀掉。
_WIN_ONLY = pytest.mark.skipif(
	sys.platform != "win32", reason="PID 归属判定依赖 tasklist 镜像名（Windows）"
)


def _ws(tmp_path: Path) -> Path:
	ws = tmp_path / "ws"
	(ws / ".xeyo").mkdir(parents=True, exist_ok=True)
	return ws


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
	"""隔离 XEYO_HOME / XEYO_CWD / 授权环境变量 + 重置管理器单例。

	不隔离的话：本机 ``~/.xeyo/settings.json`` 的 ``local_models.enabled`` 会污染
	"默认关"断言，``XEYO_ALLOW_LOCAL_MODEL`` 会让门禁用例失真。
	"""
	home = tmp_path / "home"
	home.mkdir(exist_ok=True)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.delenv("XEYO_CWD", raising=False)
	monkeypatch.delenv("XEYO_ALLOW_LOCAL_MODEL", raising=False)
	import localmodels.manager as mgr

	monkeypatch.setattr(mgr, "_MANAGER", None, raising=False)
	return home


# ---- 登记表 ----
def test_catalog_has_both_models() -> None:
	ids = [m.id for m in catalog.LOCAL_MODELS]
	assert ids == ["qwopus35-4b-coder-mtp", "lfm25-8b-a1b"]


def test_resolve_model_id_falls_back_to_default() -> None:
	assert catalog.resolve_model_id("lfm25-8b-a1b") == "lfm25-8b-a1b"
	assert catalog.resolve_model_id("nope") == catalog.default_model_id()
	assert catalog.resolve_model_id(None) == catalog.default_model_id()
	assert catalog.resolve_model_id("") == catalog.default_model_id()


# ---- 配置 ----
def test_defaults_are_closed(tmp_path: Path) -> None:
	cfg = config.store()
	assert cfg["enabled"] is False, "默认必须是关：开了就会常驻占显存"
	assert cfg["active_model"] == catalog.default_model_id()
	assert cfg["host"] == "127.0.0.1"
	assert cfg["port"] == 8080
	assert config.base_url(cfg) == "http://127.0.0.1:8080/v1"


def test_save_roundtrip_persists_base_url(tmp_path: Path) -> None:
	"""base_url 必须落盘：它是后端 SSRF 白名单认的键，派生字段不写盘 = 网络面没授权。"""
	ws = _ws(tmp_path)
	config.save({"enabled": True, "port": 8123, "ctx": 16384}, cwd=str(ws))
	data = json.loads((ws / ".xeyo" / "settings.json").read_text(encoding="utf-8"))
	section = data["local_models"]
	assert section["enabled"] is True
	assert section["port"] == 8123
	assert section["base_url"] == "http://127.0.0.1:8123/v1"
	assert section["active_model"] == catalog.default_model_id()
	# 生效值一致
	again = config.store(str(ws))
	assert again["enabled"] is True
	assert config.base_url(again) == "http://127.0.0.1:8123/v1"


def test_save_rejects_unknown_key(tmp_path: Path) -> None:
	with pytest.raises(ValueError):
		config.save({"bogus": 1}, cwd=str(_ws(tmp_path)))


def test_save_rejects_out_of_range_port(tmp_path: Path) -> None:
	with pytest.raises(ValueError):
		config.save({"port": 70000}, cwd=str(_ws(tmp_path)))
	with pytest.raises(ValueError):
		config.save({"ctx": 1}, cwd=str(_ws(tmp_path)))


def test_workspace_overrides_home(tmp_path: Path, _isolate) -> None:
	ws = _ws(tmp_path)
	config.save({"ctx": 4096})  # 无 cwd → home 级
	config.save({"ctx": 32768}, cwd=str(ws))  # workspace 更具体
	assert config.store(str(ws))["ctx"] == 32768
	assert config.store()["ctx"] == 4096


def test_store_ignores_unknown_and_illegal_values(tmp_path: Path, _isolate) -> None:
	"""盘上的坏值不能让引擎崩：未知键忽略、越界值回退默认。"""
	home = _isolate
	(home / "settings.json").write_text(
		json.dumps({"local_models": {"port": 99999, "weird": "x", "gpu_layers": "abc"}}),
		encoding="utf-8",
	)
	cfg = config.store()
	assert cfg["port"] == 8080
	assert cfg["gpu_layers"] == 99
	assert "weird" not in cfg


# ---- 授权位 ----
def test_gate_closed_by_default() -> None:
	assert gate.local_model_allowed() is False


def test_gate_opened_by_env(monkeypatch) -> None:
	monkeypatch.setenv("XEYO_ALLOW_LOCAL_MODEL", "1")
	assert gate.local_model_allowed() is True


def test_gate_opened_by_settings(tmp_path: Path) -> None:
	"""产品通道：设置面板里启用即授权，不需要环境变量。"""
	ws = _ws(tmp_path)
	assert gate.local_model_allowed(str(ws)) is False
	config.save({"enabled": True}, cwd=str(ws))
	assert gate.local_model_allowed(str(ws)) is True


# ---- 进程管理器（不真起进程）----
def test_start_without_binary_reports_actionable_error() -> None:
	res = LocalModelManager().start()
	assert res["ok"] is False
	assert "llama-server.exe" in res["error"]
	# 错误必须能指导下一步，而不是只说失败
	assert "bin" in res["error"]


def test_status_shape() -> None:
	st = LocalModelManager().status()
	assert st["state"] == "stopped"
	assert st["healthy"] is False
	assert st["base_url"].endswith("/v1")
	assert st["log_path"].endswith("llama-server.log")


def test_stop_is_idempotent() -> None:
	mgr = LocalModelManager()
	assert mgr.stop()["ok"] is True
	assert mgr.stop()["ok"] is True
	assert mgr.status()["state"] == "stopped"


# ---- PID 归属守卫（Windows 会复用 pid：拿陈旧 run.json 去杀 = 误杀无关进程）----
def test_image_name_distinguishes_gone_from_error() -> None:
	"""``""`` = 确认不存在；``None`` = 查询失败。两者不能混为一谈。"""
	assert LocalModelManager._image_name(0) == ""
	assert LocalModelManager._image_name(999_999_999) == ""


def test_pid_ownership_of_dead_pid_is_gone() -> None:
	assert LocalModelManager.pid_ownership(999_999_999) == "gone"
	assert LocalModelManager.pid_ownership(None) == "gone"
	assert LocalModelManager.pid_ownership(0) == "gone"


@_WIN_ONLY
def test_pid_ownership_current_process_is_foreign() -> None:
	"""当前测试进程是 python，不是 llama-server ⇒ foreign（绝不允许被当成 ours）。"""
	import os

	pid = os.getpid()
	assert LocalModelManager.pid_ownership(pid) == "foreign"
	assert LocalModelManager.is_llama_server_pid(pid) is False


@_WIN_ONLY
def test_cleanup_from_run_file_refuses_foreign_pid(tmp_path: Path, _isolate) -> None:
	"""兜底清理遇到"pid 已被复用给无关进程"时不得杀它，但要清掉失效记录。"""
	import os

	import localmodels.manager as mgr

	run_path = config.run_dir() / "run.json"
	run_path.parent.mkdir(parents=True, exist_ok=True)
	victim = os.getpid()  # 我们自己就是那个"被复用"的无关进程
	run_path.write_text(
		json.dumps({"pid": victim, "model": "lfm25-8b-a1b", "port": 8099}),
		encoding="utf-8",
	)

	mgr._cleanup_from_run_file()

	assert LocalModelManager._pid_alive(victim), "外来 pid 竟然被杀了"
	assert not run_path.exists(), "失效记录应当被清掉"


@_WIN_ONLY
def test_stop_refuses_foreign_pid_from_run_file(tmp_path: Path, _isolate) -> None:
	"""``stop()`` 同样不能凭 run.json 里的外来 pid 动手。"""
	import os

	run_path = config.run_dir() / "run.json"
	run_path.parent.mkdir(parents=True, exist_ok=True)
	victim = os.getpid()
	run_path.write_text(
		json.dumps({"pid": victim, "model": "lfm25-8b-a1b", "port": 8099}),
		encoding="utf-8",
	)

	res = LocalModelManager().stop()

	assert res["ok"] is True
	assert res["stopped"] is False, "没杀任何东西"
	assert LocalModelManager._pid_alive(victim)


def test_autostart_skips_when_disabled() -> None:
	res = LocalModelManager().autostart()
	assert res == {"ok": True, "skipped": "disabled"}


def _fake_install(tmp_path: Path, model_id: str) -> tuple[Path, Path]:
	"""在隔离 home 下造出"二进制 + 权重都在"的假安装，返回 (binary, gguf)。"""
	bindir = config.models_dir() / "bin"
	bindir.mkdir(parents=True, exist_ok=True)
	binary = bindir / "llama-server.exe"
	binary.write_bytes(b"")
	entry = catalog.get(model_id)
	assert entry is not None
	gguf = config.models_dir() / entry.filename
	gguf.write_bytes(b"")
	return binary, gguf


def test_build_cmd_carries_expected_flags(tmp_path: Path, _isolate) -> None:
	config.save({"ctx": 16384, "gpu_layers": 42, "port": 8099})
	_binary, gguf = _fake_install(tmp_path, "lfm25-8b-a1b")
	mgr = LocalModelManager()
	cmd = mgr._build_cmd(config.store(), "lfm25-8b-a1b")

	assert cmd[0].endswith("llama-server.exe")
	assert gguf.as_posix() in [Path(a).as_posix() for a in cmd]
	assert "-m" in cmd and cmd[cmd.index("-m") + 1].endswith(".gguf")
	assert cmd[cmd.index("--port") + 1] == "8099"
	assert cmd[cmd.index("-c") + 1] == "16384"
	assert cmd[cmd.index("-ngl") + 1] == "42"
	# alias = 模型 id，使 /v1/models 报出前端账号里登记的名字
	assert cmd[cmd.index("--alias") + 1] == "lfm25-8b-a1b"
	# --jinja：不带它 llama-server 不解析请求里的 tools，模型永远不产 tool_calls
	assert "--jinja" in cmd


def test_every_catalog_model_enables_jinja(tmp_path: Path, _isolate) -> None:
	"""工具调用是 XEYO 的动作通道：登记表里每一支都必须带 ``--jinja``。

	锁住的是"功能必需项"而非调优项——重构 ``_build_cmd`` 或新增模型时若把
	``--jinja`` 弄丢，本地模型会静默退化成"只会输出文本"，在别处很难发现。
	"""
	for m in catalog.LOCAL_MODELS:
		_fake_install(tmp_path, m.id)
		cmd = LocalModelManager()._build_cmd(config.store(), m.id)
		assert "--jinja" in cmd, f"{m.id} 缺少 --jinja：工具调用将不可用"


def test_build_cmd_reports_missing_weights(tmp_path: Path, _isolate) -> None:
	# 只放二进制、不放权重
	bindir = config.models_dir() / "bin"
	bindir.mkdir(parents=True, exist_ok=True)
	(bindir / "llama-server.exe").write_bytes(b"")
	res = LocalModelManager().start("lfm25-8b-a1b")
	assert res["ok"] is False
	assert "权重文件缺失" in res["error"]
	assert "fetch-local-models" in res["error"]


def test_extra_args_are_appended(tmp_path: Path, _isolate) -> None:
	config.save({"extra_args": "--flash-attn --no-mmap"})
	_fake_install(tmp_path, "qwopus35-4b-coder-mtp")
	cmd = LocalModelManager()._build_cmd(config.store(), "qwopus35-4b-coder-mtp")
	assert "--flash-attn" in cmd
	assert "--no-mmap" in cmd


# ---- API ----
def test_get_snapshot(tmp_path: Path) -> None:
	with TestClient(app) as c:
		r = c.get("/v1/local-models")
	assert r.status_code == 200, r.text
	body = r.json()
	assert body["ok"] is True
	assert [m["id"] for m in body["models"]] == [m.id for m in catalog.LOCAL_MODELS]
	# 隔离 home 下没有二进制，也不该有已就绪的权重
	assert body["binary"]["found"] is False
	assert all(m["present"] is False for m in body["models"])
	assert body["gate"] == {"env": False, "settings": False, "allowed": False}
	assert body["status"]["state"] == "stopped"


def test_post_settings_opens_gate(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with TestClient(app) as c:
		r = c.post(
			f"/v1/local-models?workspace={ws}",
			json={"settings": {"enabled": True, "ctx": 32768}, "workspace": str(ws)},
		)
	assert r.status_code == 200, r.text
	body = r.json()
	assert body["settings"]["ctx"] == 32768
	assert body["gate"]["settings"] is True
	assert body["gate"]["allowed"] is True


def test_post_unknown_key_is_400() -> None:
	with TestClient(app) as c:
		r = c.post("/v1/local-models", json={"settings": {"nope": 1}})
	assert r.status_code == 400


def test_switch_persists_active_model(tmp_path: Path) -> None:
	ws = _ws(tmp_path)
	with TestClient(app) as c:
		# 未运行时切换只改配置，不启进程
		r = c.post(
			f"/v1/local-models/switch?workspace={ws}",
			json={"model": "lfm25-8b-a1b", "workspace": str(ws)},
		)
	assert r.status_code == 200, r.text
	assert r.json()["settings"]["active_model"] == "lfm25-8b-a1b"
	assert config.store(str(ws))["active_model"] == "lfm25-8b-a1b"


def test_rejected_from_lan() -> None:
	with TestClient(app, client=_LAN) as c:
		assert c.get("/v1/local-models").status_code == 403
		assert c.post("/v1/local-models", json={"settings": {}}).status_code == 403
		assert c.post("/v1/local-models/start", json={}).status_code == 403
		assert c.post("/v1/local-models/stop").status_code == 403
		assert c.post("/v1/local-models/switch", json={"model": "x"}).status_code == 403
		assert c.get("/v1/local-models/log").status_code == 403
