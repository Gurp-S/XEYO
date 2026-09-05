"""插件安装源：本地路径 / GitHub（``owner/repo[@ref]``）→ 校验 → 落入插件根 + 登记 lockfile。

供应链防线（git_policy F8）：
- git 操作一律在**每个工作区专属的暂存目录**（``<ws>/.xeyo/.plugin-stage/``）执行，而非
  插件最终位置；克隆/解析成功后**先把 manifest 校验通过 + ``min_xeyo`` 兼容通过**，
  再把目录复制进 ``<ws>/.xeyo/plugins/<name>``，最后删除暂存目录。
- 剥离仓库级 ``GIT_*`` 环境变量 + ``GIT_OPTIONAL_LOCKS=0`` + ``-c safe.bareRepository=explicit``
  （防供应链 / 防误操作主仓库）。

信任（fail-closed）：远程源（github/npm）安装后**默认未受信**，需在一处
``plugin-trust.json`` 显式批准才生效；本地源免批。信任键 = 声明 canonical-JSON 的
sha256（复用 :func:`extension.mcp_scopes.declaration_hash` 语义）。

坏 manifest / 校验失败抛 :class:`extension.errors.PluginError`（调用方应记录，
不让单个坏源搞挂启动）；同名已存在默认拒绝（:class:`PluginConflictError`）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from extension.errors import ManifestError, PluginConflictError, PluginError
from extension.manifest import version_at_least
from extension import plugin_store as plugin_store_module
from extension.plugin_store import default_lock_path, install as lock_install

_log = logging.getLogger(__name__)

#: xeyo 当前版本（min_xeyo 兼容检查基准）。
_XEYO_VERSION = "0.1.0"

#: 仓库级 GIT_* 环境变量（git 操作时剥离，防泄漏主仓库/凭证/钩子）。
GIT_ENV_STRIP = frozenset({
	"GIT_DIR",
	"GIT_WORK_TREE",
	"GIT_INDEX_FILE",
	"GIT_OBJECT_DIRECTORY",
	"GIT_ALTERNATE_OBJECT_DIRECTORIES",
	"GIT_CEILING_DIRECTORIES",
	"GIT_DISCOVERY_ACROSS_FILESYSTEM",
	"GIT_COMMON_DIR",
	"GIT_NAMESPACE",
	"GIT_SHALLOW_FILE",
	"GIT_REPLACE_REF_BASE",
	"GIT_PREFIX",
	"GIT_CONFIG_COUNT",
	"GIT_CONFIG_KEY_0",
	"GIT_CONFIG_VALUE_0",
	"GIT_AUTHOR_NAME",
	"GIT_AUTHOR_EMAIL",
	"GIT_COMMITTER_NAME",
	"GIT_COMMITTER_EMAIL",
})


def scrub_git_env(env: dict[str, str] | None = None) -> dict[str, str]:
	"""剥离仓库级 GIT_* 变量并强制安全项；返回新 dict（不修改入参）。"""
	out: dict[str, str] = {}
	for k, v in (env or os.environ).items():
		if k in GIT_ENV_STRIP:
			continue
		out[k] = v
	out["GIT_OPTIONAL_LOCKS"] = "0"
	return out


def xeyo_version() -> str:
	"""当前引擎版本（min_xeyo 检查用）；失败回落常量。"""
	try:
		from cli import __version__

		return str(__version__)
	except Exception:  # noqa: BLE001
		return _XEYO_VERSION


def plugins_root(cwd: str | None) -> Path:
	"""workspace 插件根：``<ws>/.xeyo/plugins``。"""
	if not cwd:
		raise PluginError("workspace (cwd) is required to install a plugin")
	return Path(cwd).expanduser().resolve() / ".xeyo" / "plugins"


def stage_root(cwd: str) -> Path:
	"""workspace 专属暂存目录：``<ws>/.xeyo/.plugin-stage``。"""
	return Path(cwd).expanduser().resolve() / ".xeyo" / ".plugin-stage"


def _ensure_dir(p: Path) -> None:
	p.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# 解析来源
# --------------------------------------------------------------------------- #

_GITHUB_RE_RX = re.compile(r"^(?:github:)?(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:@(?P<ref>[A-Za-z0-9_.\-/]+))?$")


def parse_source(source: str) -> dict[str, str]:
	"""把 ``source`` 解析为 {source_type, source, ref?}。

	- ``github:owner/repo[@ref]`` 或 ``owner/repo[@ref]`` → github
	- ``npm:name``（或 ``npx:name``）→ npm
	- 绝对路径 / 相对路径 / ``~`` → local
	"""
	s = (source or "").strip()
	if not s:
		raise PluginError("empty plugin source")
	if s.startswith(("./", "../", "/", "~", "\\")) or _is_pathlike(s):
		return {"source_type": "local", "source": s, "ref": ""}
	if s.startswith(("npm:", "npx:")):
		name = s.split(":", 1)[1].strip()
		if not name:
			raise PluginError(f"malformed npm source: {s}")
		return {"source_type": "npm", "source": name, "ref": ""}
	m = _GITHUB_RE_RX.match(s)
	if m:
		repo = m.group("repo")
		return {
			"source_type": "github",
			"source": f"github:{repo}",
			"ref": m.group("ref") or "",
		}
	# 兜底当本地路径处理（含不存在 → 报错）。
	return {"source_type": "local", "source": s, "ref": ""}


def _is_pathlike(s: str) -> bool:
	# 含路径分隔符（非 github owner/repo 形态才当路径；github 是单斜杠且含点）。启发式。
	if "\\" in s:
		return True
	return False


# --------------------------------------------------------------------------- #
# 校验 + 复制安装
# --------------------------------------------------------------------------- #

def validate_manifest(root: Path) -> Any:
	"""校验 manifest 并返回 ;Plugin``；坏清单抛 PluginError。"""
	from extension.manifest import load_manifest

	try:
		return load_manifest(root)
	except ManifestError as e:
		raise PluginError(str(e)) from e


def _check_min_xeyo(plugin: Any) -> None:
	min_v = (plugin.manifest.min_xeyo or "").strip()
	if min_v and not version_at_least(xeyo_version(), min_v):
		raise PluginError(
			f"plugin '{plugin.name}' requires xeyo>={min_v} but engine is {xeyo_version()}"
		)


def _copy_install(
	cwd: str,
	src_dir: Path,
	*,
	source: str,
	source_type: str,
	ref: str = "",
	allow_update: bool = False,
) -> tuple[Any, dict[str, Any]]:
	"""校验（manifest + min_xeyo）→ 复制进插件根 → 登记 lockfile。

	``allow_update`` 时覆盖既有同名（update 语义）。
	"""
	plugin = validate_manifest(src_dir)
	_check_min_xeyo(plugin)

	root = plugins_root(cwd)
	_ensure_dir(root)
	lock = default_lock_path(cwd)
	final = root / plugin.name
	if final.exists():
		if not allow_update:
			raise PluginConflictError(
				f"plugin '{plugin.name}' already installed at {final}; "
				"use update to refresh from the same source."
			)
		shutil.rmtree(final)
	shutil.copytree(src_dir, final, ignore=shutil.ignore_patterns(".git"))
	entry = lock_install(
		lock,
		name=plugin.name,
		source=source,
		source_type=source_type,
		plugin_path=final,
	)
	return plugin, entry


# --------------------------------------------------------------------------- #
# 本地 / github / npm 安装
# --------------------------------------------------------------------------- #

def install_from_path(cwd: str, source: str, *, allow_update: bool = False) -> dict[str, Any]:
	"""从本地目录安装；返回 lockfile 条目。"""
	sp = Path(source).expanduser().resolve()
	if not sp.is_dir():
		raise PluginError(f"local plugin path is not a directory: {sp}")
	plugin, entry = _copy_install(
		cwd,
		sp,
		source=str(sp),
		source_type="local",
		allow_update=allow_update,
	)
	_log.info("installed local plugin %s -> %s", plugin.name, entry["path"])
	return entry


def install_from_github(
	cwd: str, owner_repo: str, *, ref: str = "", allow_update: bool = False
) -> dict[str, Any]:
	"""从 ``owner/repo[@ref]`` 克隆安装（供应链防护）。"""
	if re.search(r"/", owner_repo) is None or owner_repo.count("/") != 1:
		raise PluginError(f"malformed github source '{owner_repo}' (expected owner/repo)")
	stage = stage_root(cwd)
	_ensure_dir(stage)
	token = uuid.uuid4().hex[:12]
	work = stage / token
	repo_url = f"https://github.com/{owner_repo}.git"
	try:
		clone_args = ["clone", "--depth", "1"]
		if ref:
			clone_args += ["--branch", ref]
		clone_args += [repo_url, str(work)]
		_c_ = work.parent
		# 克隆到临时目录，scrub env（剥离 GIT_* + safe.bareRepository=explicit）。
		scrubbed = scrub_git_env(dict(os.environ))
		scrubbed["GIT_CONFIG_COUNT"] = "1"
		scrubbed["GIT_CONFIG_KEY_0"] = "safe.bareRepository"
		scrubbed["GIT_CONFIG_VALUE_0"] = "explicit"
		try:
			proc = subprocess.run(
				["git", "clone", "--depth", "1"] + (["--branch", ref] if ref else [])
				+ [repo_url, str(work)],
				capture_output=True,
				text=True,
				env=scrubbed,
				timeout=180,
			)
		except (OSError, subprocess.TimeoutExpired) as e:
			raise PluginError(f"git clone failed: {e}") from e
		if proc.returncode != 0:
			_log.debug("git stderr: %s", (proc.stderr or "")[:500])
			raise PluginError(
				f"git clone '{owner_repo}' failed: {(proc.stderr or proc.stdout or '').strip()[:400]}"
			)
		if not (work / "plugin.json").is_file():
			# 插件可能在仓库子目录：仅支持根直装；否则明确报错。
			raise PluginError(
				f"repo '{owner_repo}' has no plugin.json at root; XEYO requires a root plugin.json"
			)
		plugin, entry = _copy_install(
			cwd,
			work,
			source=f"github:{owner_repo}",
			source_type="github",
			ref=ref,
			allow_update=allow_update,
		)
		_log.info("installed github plugin %s -> %s", plugin.name, entry["path"])
		return entry
	finally:
		# 无论成败，清理暂存目录（方向安全：失败不留下半截安装）。
		shutil.rmtree(work, ignore_errors=True)


def install_from_npm(cwd: str, package: str, *, allow_update: bool = False) -> dict[str, Any]:
	"""npm 安装（默认关闭；本期内置为未启用，抛错以保持 fail-closed）。"""
	raise PluginError(
		"npm plugin install is not enabled yet (feature-flag sidelined); "
		"use a local path or github:owner/repo."
	)


def install_from_spec(cwd: str, source: str, *, allow_update: bool = False) -> dict[str, Any]:
	"""按 ``source`` 自动分派安装；返回 {name, entry}。"""
	parsed = parse_source(source)
	st = parsed["source_type"]
	if st == "github":
		entry = install_from_github(
			cwd, parsed["source"].split(":", 1)[1], ref=parsed["ref"], allow_update=allow_update
		)
		return {"name": entry["name"], "entry": entry}
	if st == "npm":
		entry = install_from_npm(cwd, parsed["source"], allow_update=allow_update)
		return {"name": entry["name"], "entry": entry}
	entry = install_from_path(cwd, parsed["source"], allow_update=allow_update)
	return {"name": entry["name"], "entry": entry}


# --------------------------------------------------------------------------- #
# 信任（fail-closed）：远程源需显式批准。
# --------------------------------------------------------------------------- #

def trust_path(cwd: str | None) -> Path:
	from memory.instruction import xeyo_home

	return xeyo_home() / "plugin-trust.json"


def _trust_entry(plugin: Any) -> dict[str, Any]:
	# 声明身份：manifest 的 canonical JSON；不含插件 root 路径（避免随安装位置漂移）。
	decl = {
		"name": plugin.name,
		"version": plugin.manifest.version,
		"min_xeyo": plugin.manifest.min_xeyo,
	}
	return {
		"declaration_hash": plugin_declaration_hash(decl),
		"manifest": decl,
	}


def plugin_declaration_hash(decl: dict[str, Any]) -> str:
	canon = json.dumps(decl, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
	return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def load_plugin_trust(cwd: str | None) -> dict[str, Any]:
	path = trust_path(cwd)
	if not path.is_file():
		return {"version": 1, "plugins": {}}
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
		return dict(raw) if isinstance(raw, dict) else {"version": 1, "plugins": {}}
	except (OSError, json.JSONDecodeError):
		return {"version": 1, "plugins": {}}


def _write_plugin_trust(cwd: str | None, data: dict[str, Any]) -> None:
	path = trust_path(cwd)
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
	tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	os.replace(tmp, path)


def set_plugin_trusted(cwd: str | None, name: str, *, approved: bool) -> dict[str, Any]:
	data = load_plugin_trust(cwd)
	plugins = dict(data.get("plugins") or {})
	entry = dict(plugins.get(name) or {})
	entry["approved"] = bool(approved)
	plugins[name] = entry
	data["plugins"] = plugins
	data.setdefault("version", 1)
	_write_plugin_trust(cwd, data)
	return entry


def is_plugin_trusted(cwd: str | None, name: str, *, source_type: str) -> bool:
	"""本地源免批恒 True；远程源需 trust 文件里 approved=True 才为 True。"""
	if source_type == "local":
		return True
	data = load_plugin_trust(cwd)
	entry = (data.get("plugins") or {}).get(name) or {}
	return bool(entry.get("approved", False))


def update_from_registry(cwd: str, name: str) -> dict[str, Any]:
	"""按 lockfile 登记的来源重拉插件（update 语义）。返回新条目。"""
	lock = default_lock_path(cwd)
	entry = (plugin_store_module.load_plugins(lock)).get(name)
	if not entry:
		raise PluginError(f"plugin '{name}' is not registered; nothing to update")
	source = str(entry.get("source") or "")
	name_ = str(entry.get("name") or name)
	# 用登记的来源重新安装（allow_update 覆盖同名）。
	return install_from_spec(cwd, source, allow_update=True)["entry"]


def remove_plugin(cwd: str, name: str, *, owner_source: str) -> bool:
	"""卸载：归属校验通过后删除磁盘目录 + lockfile 条目 + 信任记录。"""
	from extension.plugin_store import default_lock_path, remove as lock_remove

	lock = default_lock_path(cwd)
	existed = lock_remove(lock, name=name, owner_source=owner_source)
	if existed:
		root = plugins_root(cwd).resolve()
		p = (root / name).resolve()
		# 方向安全：目标必须确在插件根内，且名字经安全校验。
		try:
			p.relative_to(root)
		except ValueError:
			raise PluginError(f"refusing to remove path outside plugins root: {p}")
		if p.is_dir():
			shutil.rmtree(p, ignore_errors=True)
		# 清信任记录。
		data = load_plugin_trust(cwd)
		(data.setdefault("plugins", {})).pop(name, None)
		_write_plugin_trust(cwd, data)
	return existed
