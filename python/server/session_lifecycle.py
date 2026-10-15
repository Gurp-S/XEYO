"""会话级资源的所有权注册表（单点清理）。

## 结构性根因

删除会话的清理逻辑此前是**手写枚举**的：`server/routers/sessions.py::delete_session`
里排了七段 `try/except`，每段对应一个 per-session 持有者。这种形状的必然结果是
**每新增一个 registry 就漏一处**，而漏掉是静默的（没有任何东西会红）。实测已漏两处：

- `JobRegistry`：删会话不杀后台 job ⇒ transcript / GUI 卡片都没了，后台 Bash 还在跑；
- `synthetic_round._REQUEST_ENVS`：`api_key` / `model` / `workspace` 陈旧快照残留
  （该函数 docstring 自己写着"回溯 / 删除会话时调用"，但删除路径没调）。

## 修法

所有 per-session 持有者实现 :class:`SessionScoped`（``name`` / ``order`` /
``drop_session``），并在**自己的单例 getter 里** ``register()``；删除会话只调
:func:`drop_all`。于是"新加 registry 忘了清理"在结构上不再可能——忘了 register
的模块会被下面的元测试抓住（而不是在生产里静默泄漏）。

## 顺序是正确性要求，不是偏好

``order`` 数字越小越先清理。关键约束：**后台 job 必须先死**——job 的 ``settle``
会写 transcript，若它排在 transcript 删除之后，会把刚删掉的会话目录重建出来。
"""

from __future__ import annotations

import importlib
import logging
from typing import Callable, Protocol, runtime_checkable

_logger = logging.getLogger("xeyo.session.lifecycle")

# ---- 清理顺序阶梯（唯一权威；各 owner 的 order 必须取自这里）----------------
ORDER_JOBS = 10
ORDER_SYNTHETIC_ENV = 20
ORDER_GOAL = 30
ORDER_INBOX = 40
ORDER_RUNTIME_MODE = 50
ORDER_RUNTIME_PRESET = 60
#: 引擎实例本身（内存态）。放在各 registry 之后：先断"还会再产生工作"的通道。
ORDER_POOL = 70
#: 磁盘 transcript / 会话目录。**必须最后**（见模块 docstring 的顺序约束）。
ORDER_TRANSCRIPT = 90


@runtime_checkable
class SessionScoped(Protocol):
	"""per-session 持有者：能被按会话清理。"""

	name: str
	order: int

	def drop_session(self, session_id: str) -> None:
		"""清掉该会话在本持有者内的一切状态。实现须自行吞掉非致命异常。"""
		...


_REGISTRY: dict[str, SessionScoped] = {}
_HOOKS: dict[str, tuple[int, Callable[[str], None]]] = {}
_BUILTIN_HOOKS_DONE = False


def _drop_synthetic_request_env(session_id: str) -> None:
	from server.synthetic_round import clear_request_env

	clear_request_env(session_id)


def _drop_runtime_mode(session_id: str) -> None:
	from permissions.runtime_mode import get_runtime_mode_store

	get_runtime_mode_store().clear(session_id)


def _drop_runtime_preset(session_id: str) -> None:
	from permissions.runtime_preset import get_runtime_preset_store

	get_runtime_preset_store().clear(session_id)


def _register_builtin_hooks() -> None:
	"""登记**函数型**持有者（模块级 dict / store，没有自有类可挂 name/order）。

	这些是"没有类、因此最容易在 router 手写枚举里被漏掉"的那一批——实测漏的
	正是 synthetic_request_env（`api_key` / `model` / `workspace` 陈旧快照残留）。
	"""
	global _BUILTIN_HOOKS_DONE
	if _BUILTIN_HOOKS_DONE:
		return
	_BUILTIN_HOOKS_DONE = True
	for name, order, fn in (
		("synthetic_request_env", ORDER_SYNTHETIC_ENV, _drop_synthetic_request_env),
		("runtime_mode", ORDER_RUNTIME_MODE, _drop_runtime_mode),
		("runtime_preset", ORDER_RUNTIME_PRESET, _drop_runtime_preset),
	):
		_HOOKS.setdefault(name, (order, fn))


#: 类持有者：``(模块名, "取已建实例的函数名")``。取函数**不得**有创建副作用。
_CLASS_OWNERS: tuple[tuple[str, str], ...] = (
	("server.job_registry", "current_job_registry"),
	("server.goal_round_driver", "current_goal_round_driver"),
	("server.inbox_registry", "current_inbox_registry"),
)


def _ensure_registered() -> None:
	"""补齐登记（每次 ``drop_all`` / ``registered`` 前调用）。

	**为什么不能只靠"创建时自登记"**：单例的 register 只发生在创建那一刻。任何
	注册表被重置（测试隔离 / 模块 reload）或"先创建、后重置"的顺序，都会让那个
	单例**永久**登记不上 —— `drop_all` 于是静默漏掉它。这个缺陷是实测抓出来的：
	`test_delete_session_kills_owned_background_jobs` 单独跑绿、与其它测试同跑转红
	（前面的用例已把单例建好，随后 reset 抹掉了登记）。

	这里改为**幂等补齐**：取"已建实例"（无则跳过），有则登记。于是无论创建与
	重置的先后如何，drop_all 看到的都是完整的持有者集合。
	"""
	_register_builtin_hooks()
	for module_name, getter_name in _CLASS_OWNERS:
		try:
			module = importlib.import_module(module_name)
			getter = getattr(module, getter_name, None)
			if not callable(getter):
				continue
			instance = getter()
			if instance is not None:
				register(instance)
		except Exception:  # noqa: BLE001 — 取实例失败只是少一个持有者，不阻断清理
			_logger.debug("lifecycle owner lookup failed: %s", module_name, exc_info=True)


def register(owner: SessionScoped) -> None:
	"""登记一个持有者（幂等；同名后登记者覆盖前者）。"""
	_REGISTRY[str(owner.name)] = owner


def register_hook(name: str, order: int, fn: Callable[[str], None]) -> None:
	"""登记一个函数型清理（用于没有自有类的持有者，如模块级 dict）。"""
	_HOOKS[str(name)] = (int(order), fn)


def registered() -> tuple[tuple[str, int], ...]:
	"""已登记持有者（name, order），按清理顺序排序。供元测试与诊断。"""
	_ensure_registered()
	return tuple(
		(name, order) for name, order, _fn in _ordered_owners()
	)


def _ordered_owners() -> list[tuple[str, int, Callable[[str], None]]]:
	rows: list[tuple[str, int, Callable[[str], None]]] = []
	for owner in _REGISTRY.values():
		rows.append((str(owner.name), int(owner.order), owner.drop_session))
	for name, (order, fn) in _HOOKS.items():
		rows.append((name, order, fn))
	rows.sort(key=lambda row: (row[1], row[0]))
	return rows


def drop_all(session_id: str) -> list[tuple[str, str | None]]:
	"""按顺序清理该会话的全部已登记资源；返回 ``[(name, error|None)]``。

	**任何单个 owner 失败都不阻断后续**：删除会话的语义是"能删多少删多少，
	并把删不掉的如实报出来"。旧实现里 goal / inbox 的异常会直接 503 中断整个
	删除流程，结果是 transcript 根本没被处理——比"某一块没清掉"更糟。
	"""
	sid = (session_id or "").strip()
	if not sid:
		return []
	_ensure_registered()
	results: list[tuple[str, str | None]] = []
	for name, _order, fn in _ordered_owners():
		try:
			fn(sid)
			results.append((name, None))
		except Exception as exc:  # noqa: BLE001 — 清理失败只留痕，不阻断
			_logger.warning(
				"session cleanup failed: %s sid=%s", name, sid, exc_info=True
			)
			results.append((name, f"{type(exc).__name__}: {exc}"[:200]))
	return results


def reset_for_tests() -> None:
	"""清空注册表（仅供测试隔离；生产不得调用）。"""
	global _BUILTIN_HOOKS_DONE
	_REGISTRY.clear()
	_HOOKS.clear()
	_BUILTIN_HOOKS_DONE = False


__all__ = [
	"ORDER_GOAL",
	"ORDER_INBOX",
	"ORDER_JOBS",
	"ORDER_POOL",
	"ORDER_RUNTIME_MODE",
	"ORDER_RUNTIME_PRESET",
	"ORDER_SYNTHETIC_ENV",
	"ORDER_TRANSCRIPT",
	"SessionScoped",
	"drop_all",
	"register",
	"register_hook",
	"registered",
	"reset_for_tests",
]
