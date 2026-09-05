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
	# 机器级 XEYO_L5 / C2_GATE env 不参与运行时（get_value 语义），setenv 仅
	# 兜底历史直读残留。C2_GATE 生产默认开（用户决策 2026-09）；需 gate 关的
	# 单测用 mem_switch(XEYO_C2_GATE="0") 隔离 settings。
	monkeypatch.delenv("XEYO_L5", raising=False)
	monkeypatch.setenv("XEYO_C2_GATE", "0")
	# T27 起 aging 生产默认关（与文档「默认关」对齐）；测试环境保持显式 "0"
	# 兜底，防止机器级 env 泄漏影响 project 不变量单测。
	# test_memory_aging 等需自行 setenv("XEYO_TOOL_AGING", "1").
	monkeypatch.setenv("XEYO_TOOL_AGING", "0")


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



def pytest_collection_modifyitems(items):
	"""给通道测试打标记：fixture 按标记做单例状态隔离。"""
	for item in items:
		if "channel" in item.module.__name__:
			item.add_marker(pytest.mark.channel)


@pytest.fixture(autouse=True)
def _reset_channel_singletons(request):
	"""通道测试（filehelper/ilink）之间隔离模块级单例的「纯数据」全局。

	asyncio 原语（Event/Lock）已由两个 bridge 的惰性创建/start 重建解决；
	这里只重置 events/stream/queue 等数据态，避免前一个测试的发布物
	（状态、流文本、工具事件）泄漏到下一个测试。
	"""
	if "channel" not in request.node.iter_markers():
		yield
		return
	import channels.filehelper.service as fh_svc
	import channels.ilink.service as il_svc

	fh_svc._mirror.reset_data()
	fh_svc._inbound_q.clear()
	fh_svc._prev_complete = None
	fh_svc._channel = None

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
