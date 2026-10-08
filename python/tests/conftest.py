import os

import bootstrap  # noqa: F401
import pytest


@pytest.fixture(autouse=True)
def _isolate_xeyo_sessions(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / ".xeyo_sessions"))
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path / ".xeyo_usage"))
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	# 回溯快照 / spill 落盘同样钉进 tmp：二者默认 Path.home() 指向真实主目录
	# （rewind/snapshot.py、tools/spill.py），受限环境（只读主目录/沙箱）下
	# mkstemp 遇 PermissionError 会整组重试，表现为测试集体"挂死"。
	# 例外：test_blob_gc.py::test_snapshot_root_default 断言「无 env 时回落 ~」，
	# 该测试自行 delenv 后再断言。
	monkeypatch.setenv("XEYO_SNAPSHOTS_DIR", str(tmp_path / ".xeyo_snapshots"))
	monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path / ".xeyo_spill"))
	# journal 根以前硬编码 Path.home()/.xeyo/journal，于是测试自己造的 workspace id
	# （tmp_path 派生的 test_* / wt_*）连同派生索引一律写进用户真实主目录（实测
	# 堆到 9662 个 .jsonl）。现在与 sessions/spill 同轨钉进 tmp。
	monkeypatch.setenv("XEYO_JOURNAL_DIR", str(tmp_path / ".xeyo_journal"))
	# multi-agent 指标账（usage/multi_agent_metrics.py）默认 Path.home()/.xeyo/metrics，
	# 且不读 XEYO_HOME ⇒ 须单独钉 XEYO_METRICS_DIR。否则每跑一次套件都把测试行
	# （伪 sid / write_stale）写进用户真实指标账：实测全账 14,154 行里 2,350 行是
	# 空 sid 测试行，单次全量即新增数十行；消费者 scripts/multi_agent_gate_report.py。
	monkeypatch.setenv("XEYO_METRICS_DIR", str(tmp_path / ".xeyo_metrics"))
	# 产品开关的「环境基线」：宿主会话（agent / 受限容器）会把项目级开关桥进进程，套件于是
	# 按"这台机器怎么跑"变红（实测 XEYO_WSC=1 ⇒ 12 条；XEYO_TOOL_DENY=Agent ⇒ 8 文件 18 条）。
	# 要开的世界由用例显式申请（mem_switch / setenv），如 test_action_label_semantics。
	# 名单与原因**只在** `engine/env_switches.py` 登记一次（原先两份名单交集只有 1 ⇒ 已合并）。
	#
	# 逃生门：`XEYO_TESTS_KEEP_HOST_ENV=1` 原样保留宿主环境。存在的理由是"复现宿主红"
	# 这一件事本身——没有它就没法回答"这条红是产品回归还是这台机器怎么跑"，只能靠人肉
	# 二分（本会话 7 批红都是这么来的）。默认关：默认面 = 产品默认面。
	from engine.env_switches import isolation_pins

	if os.environ.get("XEYO_TESTS_KEEP_HOST_ENV", "").strip() not in {"1", "true", "yes", "on"}:
		for _pin_name, _pin_value in isolation_pins():
			if _pin_value is None:
				monkeypatch.delenv(_pin_name, raising=False)
			else:
				monkeypatch.setenv(_pin_name, _pin_value)
	# 审计单例按**首次调用**memoize 路径（audit/log.py::default_audit_log），只改
	# XEYO_HOME 不够：先建好的单例仍指向真实主目录 ⇒ 测试事件写进生产审计账本
	# （实测污染 34 条 notice.channel，正是往后要用来取发生率的那张表）。
	from audit.log import reset_default_audit_log

	reset_default_audit_log()
	yield
	reset_default_audit_log()


@pytest.fixture(autouse=True)
def _restore_os_environ():
	"""整份 ``os.environ`` 逐用例进出快照（与上面 contextvar 复位同一形状）。

	为什么必须整份、而不是逐个键：入口 ``cli.cwdutil.resolve_cwd()`` 现在会把
	settings 里的开关注射进 ``os.environ``（``memory_switches.apply_to_environ``，
	09-22 加的桥——GUI 之外的入口原先读不到工作区开关）。仓库自己的
	``.xeyo/settings.json`` 里写着 ``XEYO_WSC=1``，于是**任何**碰到 ``resolve_cwd`` 的用例
	都会把活路径开关点亮并留在进程里，后面的用例在没人申请的情况下换了执行链：
	实测 ``XEYO_WSC=1`` 下 ``tests/test_runtime_c2.py`` 恰好 3 条红（C2 被 WSC 接管，
	``c2_summary_text`` 变空），而单跑全绿——这种"红名单随跑序漂移"就是套件不可信的来源。
	``monkeypatch`` 只还原它自己 set 过的键，兜不住这种**被测代码自己写 env**。
	"""
	snapshot = dict(os.environ)
	try:
		yield
	finally:
		if os.environ != snapshot:
			os.environ.clear()
			os.environ.update(snapshot)


@pytest.fixture(autouse=True)
def _reset_permission_mode_ctx():
	"""权限审批模式隔离：permission_mode() 优先读模块级 ContextVar
	（set_permission_mode 写入）。若某测试 set 而未复位，会上下文泄漏到
	后续测试，导致 fail-closed / 单调性护栏单测顺序敏感（按 order 跑/单跑
	失败集不一致）。每个测试前复位为 None（env / RuntimeModeStore 兜底），
	需要显式模式的测试自行 set_permission_mode(...)。"""
	from permissions.policy import set_permission_mode

	set_permission_mode(None)
	yield
	set_permission_mode(None)


@pytest.fixture(autouse=True)
def _isolate_policy_contextvars():
	"""权限面全量隔离：permissions.policy 里**每一个** ContextVar 测后归位。
	只复位 permission_mode 会漏掉 surface / in_subagent / agent_mode 等同类
	ambient 变量——worker 泄漏事故里最危险的那个恰好不是被测出来的那个。

	「不传染后续测试」由这里兜；「检测泄漏」交给专门用例
	（tests/coord/test_worker_session.py::test_worker_session_restores_caller_ambient_state）。
	"""
	import contextvars

	from permissions import policy

	vars_ = [v for v in vars(policy).values() if isinstance(v, contextvars.ContextVar)]
	saved = {v: v.get() for v in vars_}
	try:
		yield
	finally:
		for v, value in saved.items():
			v.set(value)


@pytest.fixture
def mem_switch(monkeypatch):
	"""记忆开关单测助手：把开关经 memory_switches.get_value 覆盖（settings 语义）。

	背景：记忆开关（XEYO_L5 / C2_GATE / TOOL_AGING / C2_LLM_SUMMARY / Path A 公式等注册键）
	已改为「以 GUI settings.memory 为准、环境变量一律不参与」。运行时 getter 惰性
	``from memory.memory_switches import get_value``，故 monkeypatch 该模块属性即可。

	用法：:
	    def test_x(monkeypatch, mem_switch):
	        mem_switch(XEYO_L5="v61")        # 覆盖（等价以前 setenv）
	        # 不覆盖的键 → 落默认（等价以前 delenv）
	"""
	import memory.memory_switches as _ms

	_real = _ms.get_value
	_overrides: dict[str, str] = {}

	def _patched(key: str, cwd=None) -> str:
		if key in _overrides:
			return _overrides[key]
		return _real(key, cwd)

	monkeypatch.setattr(_ms, "get_value", _patched)

	def _set(**updates) -> None:
		_overrides.update({k: str(v) for k, v in updates.items()})

	def _reset(*keys) -> None:
		for k in keys:
			_overrides.pop(k, None)

	_set.reset = _reset  # type: ignore[attr-defined]
	return _set


@pytest.fixture(autouse=True)
def _bind_test_workspace(tmp_path):
	"""HTTP 套件：给单例 SessionPool 钉一个临时仓，避免未选 folder 时落到 python/。"""
	ws = tmp_path / "xeyo_ws"
	ws.mkdir()
	try:
		from server.deps import _pool

		_pool.set_cwd(str(ws))
	except Exception:
		pass



_SLOW_BUDGET_S = 300


def pytest_collection_modifyitems(items):
	"""给通道测试打标记：fixture 按标记做单例状态隔离。

	同时把 `slow` 翻译 pytest-timeout 认得的 `timeout` 标记：全局 `timeout = 60`
	对每个用例生效，而 markers 里 "slow: allowed up to 300s" 只是声明——不翻译，
	标了 slow 的长用例照样在 60s 被 thread 法杀掉，且杀掉的是整轮会话（不是单条红）。
	"""
	for item in items:
		if "channel" in item.module.__name__:
			item.add_marker(pytest.mark.channel)
		if (
			item.get_closest_marker("slow")
			and item.get_closest_marker("timeout") is None
		):
			item.add_marker(pytest.mark.timeout(_SLOW_BUDGET_S))


@pytest.fixture(autouse=True)
def _reset_channel_singletons(request):
	"""通道测试（ilink）之间隔离模块级单例的「纯数据」全局。

	asyncio 原语（Event/Lock）已由 bridge 的惰性创建/start 重建解决；
	这里只重置 events/stream/queue 等数据态，避免前一个测试的发布物
	（状态、流文本、工具事件）泄漏到下一个测试。
	"""
	if "channel" not in request.node.iter_markers():
		yield
		return
	import channels.ilink.service as il_svc

	il_svc._mirror.reset_data()
	il_svc._inbound_q.clear()
	il_svc._st._prev_complete = None
	il_svc._st._channel = None
	il_svc._st._msg_lock = None
	il_svc._st._last_session_id = il_svc.SESSION_ID
	il_svc._st._stream_session_id = ""
	il_svc._st._runner_ref = None
	yield


@pytest.fixture(autouse=True)
def _sidecars_unapplied():
	"""每个测试前回退侧挂挂钩。

	引擎构建（build_default_engine → sidecar.upgrade.apply）会把挂钩装进主模块且
	进程内常驻——同进程后续「默认关 / install 幂等」类断言会被污染。逐测试回退，
	让每个测试从干净基线出发（固化模块 rerank_preference 同样被回退，由各测试
	自行 install）。
	"""
	try:
		from sidecar.upgrade import unapply

		unapply()
	except Exception:  # noqa: BLE001 — 侧挂不可用时不挡测试
		pass
	yield
