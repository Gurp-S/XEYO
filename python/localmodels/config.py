"""本地模型配置：持久化到 ``.xeyo/settings.json`` 的 ``local_models`` 段。

读取姿势与 ``memory.memory_switches`` 一致：home 级 ``~/.xeyo/settings.json`` 与
工作区级 ``<ws>/.xeyo/settings.json`` 两层合并，**workspace 更具体者优先**。

与记忆开关的一处关键差别：本段的 ``enabled`` 同时是**产品授权位**——
``server/deps._resolve_base_url`` 的 SSRF 白名单按 ``base_url`` 字面匹配，
而 ``localmodels.gate.local_model_allowed`` 读 ``enabled``。两者都由本模块
写成同一份文件，所以"用户显式启用"这一个动作同时打开执行面与网络面，
不需要另设环境变量。

为什么默认关（``enabled=False``）：本地服务常驻会占显存与端口。默认关意味着
「用户没有主动开启 → 进程不存在」，即默认零日常消耗。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from extension import config as _cfg
from localmodels import catalog

SECTION = "local_models"

#: 字段 → (类型, 说明)。类型只用于归一化，非法值一律回退默认（方向安全）。
FIELDS: dict[str, Any] = {
	"enabled": (bool, "是否随 XEYO 启动本地模型服务（默认关）"),
	"active_model": (str, "当前使用的模型 id（单实例：切换 = 重启服务）"),
	"models_dir": (str, "GGUF 与二进制所在目录；空 = ~/.xeyo/local-models"),
	"binary": (str, "llama-server.exe 路径；空 = 在 models_dir 下自动探测"),
	"host": (str, "服务监听地址"),
	"port": (int, "服务监听端口"),
	"ctx": (int, "上下文长度（token）"),
	"gpu_layers": (int, "卸载到 GPU 的层数（99 = 全部）"),
	"extra_args": (str, "追加给 llama-server 的原始参数（空格分隔）"),
}

DEFAULTS: dict[str, Any] = {
	"enabled": False,
	"active_model": catalog.default_model_id(),
	"models_dir": "",
	"binary": "",
	"host": "127.0.0.1",
	"port": 8080,
	"ctx": 8192,
	"gpu_layers": 99,
	"extra_args": "",
}

#: 取值上下界（同时用于设置页校验与运行期夹取）。
BOUNDS: dict[str, tuple[int, int]] = {
	"port": (1, 65535),
	"ctx": (512, 1_048_576),
	"gpu_layers": (0, 999),
}


def home_root() -> Path:
	"""XEYO home（``~/.xeyo``，受 ``XEYO_HOME`` 影响）。"""
	from memory.instruction import xeyo_home

	return xeyo_home()


def _resolve_cwd(cwd: str | None) -> str | None:
	"""无显式 cwd 时用服务器管理的 ``XEYO_CWD`` 解析工作区设置。"""
	if cwd:
		return cwd
	return (os.environ.get("XEYO_CWD") or "").strip() or None


def models_dir() -> Path:
	"""GGUF 与二进制所在目录（显式配置 > 默认 ``~/.xeyo/local-models``）。"""
	raw = str(store().get("models_dir") or "").strip()
	return Path(raw).expanduser() if raw else (home_root() / "local-models")


def run_dir() -> Path:
	"""运行期文件（PID / 日志）目录。"""
	return home_root() / "local-models" / "run"


def _raw(cwd: str | None = None) -> dict[str, Any]:
	"""合并 home + workspace 的 ``local_models`` 段（workspace 覆盖 home）。"""
	home = _cfg._read_json(_cfg.home_settings_path())  # noqa: SLF001
	merged = dict(home.get(SECTION) or {})
	ws_cwd = _resolve_cwd(cwd)
	if ws_cwd:
		try:
			ws = _cfg._read_json(_cfg.workspace_settings_path(ws_cwd))  # noqa: SLF001
		except Exception:  # noqa: BLE001 — 工作区不可解析时退化为 home 层
			ws = {}
		merged.update(ws.get(SECTION) or {})
	return merged


def _coerce(key: str, raw: Any) -> Any:
	"""把原始值归一化到字段类型；非法返回 None（调用方回退默认）。"""
	typ, _ = FIELDS.get(key, (str, ""))
	if key == "enabled":
		if isinstance(raw, bool):
			return raw
		return str(raw).strip().lower() in ("1", "true", "on", "yes", "enabled")
	try:
		val = raw if isinstance(raw, typ) else typ(raw)
	except (TypeError, ValueError):
		return None
	if typ is str:
		val = val.strip()
	elif typ is int:
		lo, hi = BOUNDS.get(key, (None, None))  # type: ignore[misc]
		if lo is not None and not (lo <= val <= hi):
			return None
	# 空字符串对 models_dir/binary/extra_args 是合法值（= 用默认/不追加）。
	if key in ("models_dir", "binary", "extra_args") and not str(raw).strip():
		return ""
	if key == "host":
		return val or DEFAULTS["host"]
	return val


def store(cwd: str | None = None) -> dict[str, Any]:
	"""生效配置 = 默认 ← settings 段（逐字段归一化，非法字段回退默认）。"""
	out = dict(DEFAULTS)
	for key, raw in _raw(cwd).items():
		if key not in FIELDS:
			continue  # 未知键忽略（不报错：旧版本残留不应阻断启动）
		coerced = _coerce(key, raw)
		if coerced is not None:
			out[key] = coerced
	out["active_model"] = catalog.resolve_model_id(str(out.get("active_model") or ""))
	return out


def base_url(cfg: dict[str, Any] | None = None) -> str:
	"""本地服务 OpenAI 兼容基址（``http://host:port/v1``）。"""
	c = cfg or store()
	return f"http://{c['host']}:{int(c['port'])}/v1"


def resolve_binary(cfg: dict[str, Any] | None = None) -> Path | None:
	"""llama-server 可执行文件路径；找不到返回 None。

	探测顺序：显式配置 → ``models_dir/bin`` 及其一级子目录（官方 Windows 压缩包
	解压后会带一层 ``llama-bXXXX-bin-...`` 目录）→ ``models_dir`` 自身。
	"""
	c = cfg or store()
	explicit = str(c.get("binary") or "").strip()
	if explicit:
		p = Path(explicit).expanduser()
		return p if p.is_file() else None
	root = models_dir()
	candidates: list[Path] = []
	binroot = root / "bin"
	candidates.append(binroot / "llama-server.exe")
	if binroot.is_dir():
		for child in sorted(binroot.iterdir()):
			if child.is_dir():
				candidates.append(child / "llama-server.exe")
				for grand in sorted(child.iterdir()):
					if grand.is_dir():
						candidates.append(grand / "llama-server.exe")
	candidates.append(root / "llama-server.exe")
	for cand in candidates:
		if cand.is_file():
			return cand
	return None


def model_path(model_id: str, cfg: dict[str, Any] | None = None) -> Path:
	"""某支模型的 GGUF 绝对路径（不保证存在）。"""
	m = catalog.get(catalog.resolve_model_id(model_id))
	name = m.filename if m else ""
	return models_dir() / name


def save(updates: dict[str, Any], cwd: str | None = None) -> dict[str, Any]:
	"""写 settings 的 ``local_models`` 段并返回生效配置。

	写两处之一：给了 cwd 写工作区级，否则写 home 级（与记忆开关同款原子写）。
	``base_url`` 一并落盘——它是 ``server/deps._is_user_configured_base_url`` 认的
	白名单键，派生字段不写盘就等于网络面没授权。
	"""
	ws_cwd = _resolve_cwd(cwd) if cwd else None
	target = (
		_cfg.workspace_settings_path(ws_cwd)  # noqa: SLF001
		if ws_cwd
		else _cfg.home_settings_path()
	)
	data = _cfg._read_json(target)  # noqa: SLF001
	section = dict(data.get(SECTION) or {})
	for key, val in updates.items():
		if key not in FIELDS:
			raise ValueError(f"未知本地模型配置项 {key!r}")
		coerced = _coerce(key, val)
		if coerced is None:
			raise ValueError(f"{key} 取值非法: {val!r}")
		section[key] = coerced
	# 归一化后回写，保证盘上永远是可解析的字面值（含 active_model 的存在性）。
	section["active_model"] = catalog.resolve_model_id(
		str(section.get("active_model") or "")
	)
	for key, default in DEFAULTS.items():
		section.setdefault(key, default)
	section["base_url"] = base_url({**DEFAULTS, **section})
	data[SECTION] = section
	_cfg.write_settings(target, data)  # noqa: SLF001
	return store()
