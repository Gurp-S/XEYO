"""文件系统权限检查（Windows 优先，XEYO P0）。"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator

_preapproved_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
	"xeyo_permission_preapproved", default=False
)


def permission_preapproved() -> bool:
	"""Registry 已 ALLOW / skip_ask 后执行工具时为 True，避免工具内 ASK→DENY。"""
	return bool(_preapproved_ctx.get())


@contextmanager
def mark_permission_preapproved(value: bool = True) -> Iterator[None]:
	"""标记当前执行已通过 registry 策略裁决（含用户确认后的 skip_ask）。"""
	token = _preapproved_ctx.set(bool(value))
	try:
		yield
	finally:
		_preapproved_ctx.reset(token)


class PermissionDecision(str, Enum):
	ALLOW = "allow"
	DENY = "deny"
	ASK = "ask"


@dataclass
class ToolPermissionContext:
	"""工具权限上下文（最小字段）。"""

	cwd: str = "."
	allowed_working_paths: list[str] = field(default_factory=list)
	extra: dict[str, Any] = field(default_factory=dict)


def default_permission_context(cwd: str | None = None) -> ToolPermissionContext:
	"""构造最小权限上下文。

	显式传入 cwd 时以其为准；为空时优先读会话级 WorkspaceContext，
	避免多并发会话读取模块级全局 cwd 而串目录。
	"""
	base = (cwd or "").strip()
	ctx = None
	if not base:
		from engine.workspace_context import get_cwd, get_workspace_context

		ctx = get_workspace_context()
		base = (ctx.cwd if ctx is not None and ctx.cwd else get_cwd()) or ""
	root = os.path.abspath(os.path.expanduser(base or os.getcwd()))
	allowed = [root]
	if ctx is not None and ctx.allowed_paths:
		allowed = [os.path.abspath(os.path.expanduser(p)) for p in ctx.allowed_paths]
	return ToolPermissionContext(cwd=root, allowed_working_paths=allowed)


# 高危文件名（basename，大小写不敏感）
DANGEROUS_FILES = frozenset(
	{
		".env",
		".env.local",
		".env.production",
		".gitconfig",
		".git-credentials",
		".netrc",
		".npmrc",
		".pypirc",
		"id_rsa",
		"id_ed25519",
		"id_ecdsa",
		"id_dsa",
		"credentials.json",
		"credentials",
	}
)

# 高危目录名（路径任一组件）
DANGEROUS_DIRECTORIES = frozenset(
	{
		".git",
		".ssh",
		".kube",
		".gnupg",
		".aws",
	}
)

# 凭据目录（is_secret_path 硬 DENY 扫描）。刻意不含 .git——.git 的读写保护
# 走 protected-metadata(workspace 内)/is_dangerous_path(工具),避免把"读 .git 需
# 确认"的整体语义变成无条件 DENY(G77/G78 修正后口径)。
_SECRET_DIRECTORIES = frozenset(
	{
		".ssh",
		".kube",
		".gnupg",
		".aws",
	}
)

DANGEROUS_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def normalize_case_for_comparison(path: str) -> str:
	"""Windows 大小写不敏感比较。"""
	return path.lower()


def expand_to_abs(path: str, *, cwd: str | None = None) -> str:
	"""相对路径相对 cwd 展开，再 abspath（防 .. 穿越）。"""
	base = os.path.abspath(os.path.expanduser(cwd or os.getcwd()))
	p = os.path.expanduser(str(path).strip())
	if not os.path.isabs(p):
		p = os.path.join(base, p)
	return os.path.abspath(p)


def path_in_allowed_working_path(
	path: str,
	*,
	cwd: str | None = None,
	allowed_working_paths: list[str] | None = None,
) -> bool:
	"""路径是否落在允许的工作目录内（Windows 大小写不敏感）。

	两侧都按 realpath 解析：工作区内的符号链接若指向外部目标，
	比较时落在真实目标上，防止借 symlink 逃出工作区写文件。
	"""
	base = os.path.abspath(os.path.expanduser(cwd or os.getcwd()))
	abs_path = normalize_case_for_comparison(
		os.path.realpath(expand_to_abs(path, cwd=base))
	)
	roots = allowed_working_paths
	if not roots:
		roots = [base]
	for root in roots:
		abs_root = normalize_case_for_comparison(
			os.path.realpath(os.path.abspath(os.path.expanduser(root)))
		)
		if abs_path == abs_root or abs_path.startswith(abs_root + os.sep):
			return True
		# 也接受 / 风格前缀（混合分隔符）
		if abs_path.startswith(abs_root.rstrip("\\/") + "/"):
			return True
	return False


def is_secret_path(path: str, *, cwd: str | None = None) -> bool:
	"""凭据/密钥路径：硬门禁默认 DENY（不可经 ASK 放行）。"""
	abs_path = expand_to_abs(path, cwd=cwd)
	base_l = os.path.basename(abs_path).lower()
	if base_l in DANGEROUS_FILES:
		return True
	if base_l.startswith(".env") and not any(
		# 常见模板/示例后缀不含真凭据,不误伤
		base_l.endswith(s)
		for s in (".example", ".sample", ".template", ".dist")
	):
		return True  # .env 任意变体（G77: 原仅 3 个显式条目）
	if any(base_l.endswith(suf) for suf in DANGEROUS_SUFFIXES):
		return True
	norm = abs_path.replace("/", os.sep).replace("\\", os.sep)
	for part in norm.split(os.sep):
		if part.lower() in _SECRET_DIRECTORIES:
			return True
	return False


def is_dangerous_path(path: str, *, cwd: str | None = None) -> bool:
	"""危险文件名或路径组件（.git / .ssh / 密钥等）。"""
	if is_secret_path(path, cwd=cwd):
		return True
	abs_path = expand_to_abs(path, cwd=cwd)
	# 拆分组件（同时认 / 与 \）
	norm = abs_path.replace("/", os.sep).replace("\\", os.sep)
	for part in norm.split(os.sep):
		if part.lower() in DANGEROUS_DIRECTORIES:
			return True
	return False


def readable_extra_roots(*, cwd: str | None = None) -> list[str]:
	"""Grep/Read 可直读的系统路径（设计：一切"读"行为统一走现有读工具）。

	仅用于**读**裁决；写裁决不得包含。当前含：
	- 当前工作区的记忆库目录 ~/.xeyo/memory/{workspace_id}
	- **仅当前会话**的转录文件（jsonl 及其 .old1/.old2 归档）——
	  不放宽整个 sessions 目录，其他会话的转录保持不可达。
	失败静默返回空——权限门永不因辅助目录计算而崩。
	"""
	roots: list[str] = []
	c = ""
	try:
		from engine.workspace_context import get_cwd as ws_get_cwd
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		if cwd and str(cwd).strip():
			c = os.path.abspath(os.path.expanduser(cwd))
		elif ctx is not None and ctx.cwd:
			c = os.path.abspath(ctx.cwd)
		else:
			c = os.path.abspath(ws_get_cwd() or "")
	except Exception:
		c = ""
	if not c and cwd:
		try:
			c = os.path.abspath(os.path.expanduser(cwd))
		except Exception:
			c = ""
	if c:
		try:
			from memory.memdir import USER_MEMDIR_ID, memdir_root, workspace_id

			roots.append(str(memdir_root(workspace_id(c))))
			roots.append(str(memdir_root(USER_MEMDIR_ID)))
		except Exception:
			pass
	try:
		from engine.workspace_context import get_workspace_context
		from session.persistence import transcript_path
		from session.record_transcript import rotated_transcript_paths

		ctx = get_workspace_context()
		sid = (ctx.session_id if ctx is not None else "") or ""
		if sid.strip():
			tp = transcript_path(sid)
			if tp.is_file():
				roots.append(str(tp))
			for p in rotated_transcript_paths(tp):
				if p.is_file():
					roots.append(str(p))
	except Exception:
		pass
	return [r for r in roots if r]


def _max_outside_allowed() -> bool:
	"""最高档（never/allow=免确认）是否允许越出工作区读/写。

	延迟读 policy（避免 filesystem % policy 模块级循环 import；调用时两者已加载）。
	仅放宽「工作区外」这一**权限级**边界；密钥/危险路径仍按下文硬拦/ASK。
	"""
	try:
		from permissions.policy import is_max_permission_mode

		return is_max_permission_mode()
	except Exception:  # noqa: BLE001 — 权限模式读取失败不放松（默认区外 DENY）
		return False


def check_read_permission_for_path(
	path: str,
	*,
	context: ToolPermissionContext | None = None,
) -> PermissionDecision:
	"""按路径做读权限裁决。"""
	ctx = context or default_permission_context()
	cwd = ctx.cwd
	allowed = list(ctx.allowed_working_paths or [cwd])
	allowed.extend(readable_extra_roots(cwd=cwd))
	if not path_in_allowed_working_path(
		path,
		cwd=cwd,
		allowed_working_paths=allowed,
	):
		# 区外：默认 DENY；max 档放宽（如跨目录找日志），但密钥/危险仍拦截。
		if not _max_outside_allowed():
			return PermissionDecision.DENY
	# 密钥/凭据：硬 DENY（不走 ASK）。
	if is_secret_path(path, cwd=cwd):
		return PermissionDecision.DENY
	if is_dangerous_path(path, cwd=cwd):
		return PermissionDecision.ASK
	return PermissionDecision.ALLOW


def check_write_permission_for_path(
	path: str,
	*,
	context: ToolPermissionContext | None = None,
) -> PermissionDecision:
	"""按路径做写权限裁决。

	密钥路径硬 DENY；受保护元数据（.git/.xeyo/.agents，T12）硬 DENY；
	其余与读同级（危险 → ASK，区外 → DENY）。
	"""
	ctx = context or default_permission_context()
	cwd = ctx.cwd
	if is_secret_path(path, cwd=cwd):
		return PermissionDecision.DENY
	if protected_metadata_reason(path, cwd=cwd) is not None:
		return PermissionDecision.DENY
	return check_read_permission_for_path(path, context=ctx)


# ── T12：workspace 内受保护元数据（WritableRoot 语义）──────────

#: workspace 根内这些顶层目录默认只读（写请求 DENY；可 env 放宽）。
PROTECTED_METADATA_NAMES = frozenset({".git", ".xeyo", ".agents"})
ENV_ALLOW_PROTECTED_METADATA = "XEYO_ALLOW_PROTECTED_METADATA"

_PROTECTED_REASON = (
	"protected metadata: {name}/ is read-only（受保护元数据默认只读；"
	"如需放宽设置 XEYO_ALLOW_PROTECTED_METADATA=1）"
)


def _protected_metadata_allowed() -> bool:
	raw = os.environ.get(ENV_ALLOW_PROTECTED_METADATA, "").strip().lower()
	return raw in ("1", "true", "on", "yes")


def protected_metadata_reason(path: str, *, cwd: str | None = None) -> str | None:
	"""路径命中 workspace 受保护元数据时返回 reason；否则 None。

	- 约束 workspace 根内的 **任一路径组件** 命中 .git/.xeyo/.agents 即 DENY
	  （G78: 原只查首组件,`sub/.git` 被降级为 ASK——嵌套仓库/子模块的
	  git 元数据与顶层同等受保护）;workspace 外的路径交由既有边界检查处理;
	- 大小写不敏感（Windows 友好）;
	- ``XEYO_ALLOW_PROTECTED_METADATA=1`` 显式放宽。
	"""
	if _protected_metadata_allowed():
		return None
	root = (cwd or "").strip()
	if not root:
		return None
	try:
		abs_path = os.path.abspath(os.path.expanduser(path))
		abs_root = os.path.abspath(os.path.expanduser(root))
		rel = os.path.relpath(abs_path, abs_root)
	except (OSError, ValueError):
		return None
	norm = os.path.normcase(rel)
	if norm.startswith(".."):
		return None
	for part in norm.split(os.sep):
		pn = part.strip()
		if not pn:
			continue
		for name in PROTECTED_METADATA_NAMES:
			if pn == os.path.normcase(name):
				return _PROTECTED_REASON.format(name=name)
	return None


def enforce_decision(
	decision: PermissionDecision,
) -> tuple[PermissionDecision, str]:
	"""
	P0：ASK 降级为 DENY（无 UI 确认）。
	返回 (allow|deny, reason_key)。
	"""
	if decision == PermissionDecision.ALLOW:
		return PermissionDecision.ALLOW, "allowed"
	if decision == PermissionDecision.ASK:
		return PermissionDecision.DENY, "needs_confirmation"
	return PermissionDecision.DENY, "denied"


def _tool_cwd(tool: Any, context: ToolPermissionContext | None) -> str:
	if context is not None and context.cwd:
		return os.path.abspath(context.cwd)
	cwd = getattr(tool, "_cwd", None)
	if isinstance(cwd, str) and cwd.strip():
		return os.path.abspath(cwd)
	return os.path.abspath(os.getcwd())


def _extract_path_from_input(input_data: Any) -> str | None:
	"""从工具 input dataclass / dict 取路径字段；缺省 None（表示用 cwd）。"""
	if input_data is None:
		return None
	if isinstance(input_data, dict):
		for key in ("file_path", "path", "filePath", "notebook_path"):
			val = input_data.get(key)
			if isinstance(val, str) and val.strip():
				return val.strip()
		return None
	for key in ("file_path", "path", "notebook_path"):
		val = getattr(input_data, key, None)
		if isinstance(val, str) and val.strip():
			return val.strip()
	return None


def check_read_permission_for_tool(
	tool: Any,
	input_data: Any = None,
	context: ToolPermissionContext | None = None,
) -> bool:
	"""Glob / Grep / Read 等工具级读权限入口。

	只做路径裁决：ALLOW 放行；DENY 拒绝。
	ASK 仅在 registry 已批准（preapproved）时放行，不再二次把 ASK 降成 DENY 语义混淆——
	未批准的 ASK 直接 False，由 registry 挂起流程负责。
	"""
	cwd = _tool_cwd(tool, context)
	ctx = context or default_permission_context(cwd)
	raw = _extract_path_from_input(input_data)
	path = raw if raw else cwd
	decision = check_read_permission_for_path(path, context=ctx)
	if decision == PermissionDecision.ALLOW:
		return True
	if decision == PermissionDecision.ASK:
		return permission_preapproved()
	return False


def check_write_permission_for_tool(
	tool: Any,
	input_data: Any = None,
	context: ToolPermissionContext | None = None,
) -> bool:
	"""Write / Edit 等工具级写权限入口（同读：ASK 只信 registry preapproved）。"""
	cwd = _tool_cwd(tool, context)
	ctx = context or default_permission_context(cwd)
	raw = _extract_path_from_input(input_data)
	if not raw:
		return False
	decision = check_write_permission_for_path(raw, context=ctx)
	if decision == PermissionDecision.ALLOW:
		return True
	if decision == PermissionDecision.ASK:
		return permission_preapproved()
	return False
