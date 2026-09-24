"""CLI 边缘用例：路径段注入、收据诚实性、退出码、GBK/ASCII 控制台、富文本转义。

约定（与 tests/test_cli.py 一致）：
* 用 ``typer.testing.CliRunner`` 驱真实 Typer app；HTTP 面一律走
  ``httpx.MockTransport``——绝不启服务、绝不绑端口。
* 只有编码一项必须用真子进程复现：测试自己的 stdout 不是 GBK 终端。
* 断言消息一律 ASCII 折叠（Windows 控制台是 cp936，测试里 print 中文会自己炸）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import httpx
import pytest
from typer.testing import CliRunner

from cli.main import app

PY_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()

#: 服务端 delete_session 归档门槛的中文原文（server/routers/sessions.py）。
_CN_REFUSAL = "会话尚未归档：请先归档，再从已归档列表中删除"


def _ascii(text: str) -> str:
	return text.encode("ascii", "replace").decode("ascii")


class _Recorder:
	"""MockTransport 替身：记录请求 + 按序回放预设响应。"""

	def __init__(self, responses: Iterable[tuple[int, Any]]) -> None:
		self.requests: list[httpx.Request] = []
		self._responses = list(responses)

	def client(self, base_url: str = "http://127.0.0.1:8000") -> httpx.Client:
		def _handle(request: httpx.Request) -> httpx.Response:
			self.requests.append(request)
			idx = min(len(self.requests) - 1, len(self._responses) - 1)
			status, body = self._responses[idx]
			if isinstance(body, (dict, list)):
				return httpx.Response(status, json=body)
			return httpx.Response(status, text=str(body))

		return httpx.Client(transport=httpx.MockTransport(_handle), base_url=base_url)

	@property
	def paths(self) -> list[str]:
		return [r.url.path for r in self.requests]


@pytest.fixture
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
	home = tmp_path / "home"
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path / "usage"))
	monkeypatch.setenv("XEYO_SERVER_URL", "http://127.0.0.1:8000")
	return home


def _patch_client(monkeypatch: pytest.MonkeyPatch, rec: _Recorder) -> None:
	"""把 sessions_cmd 的建连换成 MockTransport（不触网、不绑端口）。"""
	monkeypatch.setattr(
		"cli.sessions_cmd.http_api.make_client",
		lambda base_url, api_key="", timeout=60.0: rec.client(base_url),
	)


# --------------------------------------------------------------------------
# 1. session id 直接拼进 URL 路径段 → 打到别的资源（破坏性）
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
	"bad_id",
	[
		"a/agents/b/inbox/c",      # DELETE /v1/sessions/{id}/agents/{aid}/inbox/{iid}
		"../../etc/passwd",        # 逃出 /v1/sessions 前缀
		"x?also=1",                # 变成查询串
		"x#frag",                  # 变成片段，资源被截断
		"",                        # 空 id
		" pad ",                   # 前后空白（服务端同样 422）
		"x" * 200,                 # 超长
	],
)
def test_rm_refers_only_the_session_route_it_names(bad_id: str, _home, monkeypatch) -> None:
	rec = _Recorder([(200, {"ok": True, "removed": []})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "rm", bad_id])
	assert res.exit_code == 2, f"rc={res.exit_code} out={_ascii(res.stdout)}"
	# 守卫的本质：一个请求都不该发出去。摘掉守卫 → 这里会看到真实路径。
	assert rec.requests == [], f"requests leaked to {_ascii(str(rec.paths))}"


@pytest.mark.parametrize("bad_id", ["a/b", "../../etc/passwd"])
def test_show_refers_only_the_session_route_it_names(bad_id: str, _home, monkeypatch) -> None:
	rec = _Recorder([(200, {"messages": []})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "show", bad_id])
	assert res.exit_code == 2, f"rc={res.exit_code} out={_ascii(res.stdout)}"
	assert rec.requests == [], f"requests leaked to {_ascii(str(rec.paths))}"


def test_legit_session_ids_still_work(_home, monkeypatch) -> None:
	"""合法字符集（含 ``:`` 与 ``.``）不许被挡——过度收紧就是回归。"""
	rec = _Recorder([(200, {"ok": True, "removed": ["/t/sess_x.jsonl"]})])
	_patch_client(monkeypatch, rec)
	for sid in ("sess_abc", "bg:task:7", "a.b-c_d"):
		res = runner.invoke(app, ["sessions", "rm", sid])
		assert res.exit_code == 0, _ascii(res.stdout)
	assert len(rec.requests) == 3, _ascii(str(rec.paths))
	assert rec.paths[-1] == "/v1/sessions/a.b-c_d"
	assert "removed 1 file" in res.stdout


# --------------------------------------------------------------------------
# 2. 收据诚实性：ok:false / 部分失败 / 认不出的响应体
# --------------------------------------------------------------------------

def test_rm_surfaces_the_servers_own_refusal_reason(_home, monkeypatch) -> None:
	rec = _Recorder([(409, {"detail": _CN_REFUSAL})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "rm", "sess_x"])
	assert res.exit_code == 1, _ascii(res.stdout)
	# 修复前只有 "409 Conflict"：用户不知道为什么删不掉。
	assert _ascii(_CN_REFUSAL)[:12] in _ascii(res.stdout), _ascii(res.stdout)


def test_rm_does_not_claim_success_when_server_says_not_ok(_home, monkeypatch) -> None:
	rec = _Recorder([(200, {"ok": False, "detail": "busy"})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "rm", "sess_x"])
	assert res.exit_code == 1, _ascii(res.stdout)
	assert "deleted" not in res.stdout, _ascii(res.stdout)


def test_rm_reports_partial_cleanup_failures(_home, monkeypatch) -> None:
	rec = _Recorder([
		(200, {"ok": True, "removed": ["a.jsonl"], "removal_errors": [{"path": "b", "err": "busy"}]}),
	])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "rm", "sess_x"])
	assert res.exit_code == 1, _ascii(res.stdout)
	assert "cleanup failure" in res.stdout, _ascii(res.stdout)


def test_rm_says_nothing_about_counts_it_does_not_know(_home, monkeypatch) -> None:
	"""缺失 ≠ 零：服务端没回 removed 列表时不许印 'removed 0'。"""
	rec = _Recorder([(200, {"ok": True})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "rm", "sess_x"])
	assert res.exit_code == 0, _ascii(res.stdout)
	assert "removed 0" not in res.stdout, _ascii(res.stdout)
	assert "deleted sess_x" in res.stdout


def test_list_rejects_an_unrecognised_body_instead_of_calling_it_empty(
	_home, monkeypatch
) -> None:
	rec = _Recorder([(200, {"ok": True})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "list"])
	assert res.exit_code == 1, _ascii(res.stdout)
	assert "no sessions" not in res.stdout, _ascii(res.stdout)
	# 必须是「认不出这个响应体」，不是 TypeError 之类顺口漏出来的实现细节。
	assert "no 'sessions' field" in " ".join(res.stdout.split()), _ascii(res.stdout)


def test_list_reports_no_sessions_without_inventing_a_disk_claim(
	_home, monkeypatch
) -> None:
	rec = _Recorder([(200, {"sessions": []})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "list"])
	assert res.exit_code == 0, _ascii(res.stdout)
	assert "server reported no sessions" in res.stdout, _ascii(res.stdout)
	# 服务端只报了「没有会话」，CLI 无权断言磁盘上也没有。
	assert "on disk" not in res.stdout


# --------------------------------------------------------------------------
# 3. 打印数据不得被当成样式（rich markup）
# --------------------------------------------------------------------------

def test_list_renders_bracket_titles_as_text(_home, monkeypatch) -> None:
	rec = _Recorder([(200, {"sessions": [{"id": "s1", "title": "hi [/oops]"}]})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "list"])
	assert res.exception is None, _ascii(str(res.exception))
	assert res.exit_code == 0, _ascii(res.stdout)
	assert "[/oops]" in res.stdout, _ascii(res.stdout)


def test_show_renders_bracket_content_as_text(_home, monkeypatch) -> None:
	rec = _Recorder([
		(200, {"messages": [{"role": "user", "content": "see [/bold] docs"}]}),
	])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "show", "s1"])
	assert res.exception is None, _ascii(str(res.exception))
	assert "[/bold]" in res.stdout, _ascii(res.stdout)


# --------------------------------------------------------------------------
# 4. --limit / 数值参数：非法值就地退出，不带着它继续跑
# --------------------------------------------------------------------------

def test_show_rejects_negative_limit(_home, monkeypatch) -> None:
	rec = _Recorder([(200, {"messages": []})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "show", "s1", "--limit", "-5"])
	assert res.exit_code == 2, _ascii(res.stdout)
	# 修复前：limit<0 时 msgs[-(-5):] 变成「跳过前 5 条」，且一个请求都不该发。
	assert rec.requests == [], _ascii(str(rec.paths))


def test_show_limit_zero_means_everything(_home, monkeypatch) -> None:
	msgs = [{"role": "user", "content": f"m{i}"} for i in range(30)]
	rec = _Recorder([(200, {"messages": msgs})])
	_patch_client(monkeypatch, rec)
	res = runner.invoke(app, ["sessions", "show", "s1", "--limit", "0"])
	assert res.exit_code == 0, _ascii(res.stdout)
	assert "showing last 30/30" in res.stdout, _ascii(res.stdout)


def test_coord_rejects_negative_counters_without_running(_home, monkeypatch) -> None:
	seen: list[dict[str, Any]] = []
	monkeypatch.setattr(
		"cli.coord_cmd.run_coord_run", lambda **kw: seen.append(kw)
	)
	res = runner.invoke(app, ["coord", "run", "--tasks", "-3"])
	assert res.exit_code == 2, _ascii(res.stdout + str(res.exception))
	assert seen == [], "bad --tasks reached the worker loop"
	res = runner.invoke(app, ["coord", "run", "--idle-poll", "-1"])
	assert res.exit_code == 2, _ascii(res.stdout + str(res.exception))
	assert seen == [], "bad --idle-poll reached time.sleep(-1)"


def test_serve_rejects_out_of_range_port(_home, monkeypatch) -> None:
	seen: list[dict[str, Any]] = []
	monkeypatch.setattr(
		"cli.serve_cmd.run_serve", lambda **kw: seen.append(kw)
	)
	res = runner.invoke(app, ["serve", "--port", "70000"])
	assert res.exit_code == 2, _ascii(res.stdout + str(res.exception))
	assert seen == [], "out-of-range port reached the server"


@pytest.mark.parametrize(
	"argv",
	[
		["chat", "--permission-mode", "neverr", "--print", "hi"],
		["chat", "--agent-mode", "pna", "--print", "hi"],
	],
)
def test_mode_options_are_validated_at_the_edge(argv, _home, monkeypatch) -> None:
	"""未知模式下游是静默归一（--agent-mode pna → agent），脚本拿不到错误。"""
	called: list[Any] = []
	monkeypatch.setattr("cli.chat_cmd.run_chat", lambda **kw: called.append(kw) or 0)
	res = runner.invoke(app, argv)
	assert res.exit_code == 2, _ascii(res.stdout + str(res.exception))
	assert called == [], "an unknown mode reached the engine"


# --------------------------------------------------------------------------
# 5. 一次性（脚本/管道）路径：退出码就是收据
# --------------------------------------------------------------------------


class _StubEngine:
	def __init__(self, events: list[Any], *, boom: bool = False) -> None:
		self.session_id = "stub-1"
		self._events = events
		self._boom = boom
		self.interrupted = False

	def submit(self, _prompt: str, _opts: Any = None):
		events, boom = self._events, self._boom

		async def _gen():
			for ev in events:
				yield ev
			if boom:
				raise RuntimeError("provider exploded [red]")

		return _gen()

	def interrupt(self) -> None:
		self.interrupted = True


def _drive_one_shot(
	monkeypatch: pytest.MonkeyPatch,
	tmp_path: Path,
	*,
	engine: Any = None,
	extra: list[str] | None = None,
) -> Any:
	monkeypatch.setenv("XEYO_NO_SESSION_PERSISTENCE", "1")
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	cwd = tmp_path / "ws"
	cwd.mkdir(exist_ok=True)
	if engine is not None:
		monkeypatch.setattr("cli.chat_cmd.build_chat_engine", lambda **kw: (engine, 0))
	return runner.invoke(
		app,
		[
			"chat", "--provider", "fake", "--cwd", str(cwd),
			"--print", "--json", *(extra or []), "hi",
		],
	)


def test_one_shot_error_result_exits_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	from msgtypes.events import ResultEvent

	res = _drive_one_shot(
		monkeypatch, tmp_path,
		engine=_StubEngine([ResultEvent(subtype="error_during_execution", is_error=True)]),
	)
	assert res.exit_code == 1, f"a failed turn must not exit 0: {res.exit_code}"


def test_one_shot_success_result_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	from msgtypes.events import ResultEvent

	res = _drive_one_shot(
		monkeypatch, tmp_path, engine=_StubEngine([ResultEvent(subtype="success")])
	)
	assert res.exit_code == 0, _ascii(res.stdout + str(res.exception))


def test_one_shot_engine_exception_is_a_clean_error_not_a_traceback(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	res = _drive_one_shot(monkeypatch, tmp_path, engine=_StubEngine([], boom=True))
	assert res.exit_code == 1, str(res.exit_code)
	assert not isinstance(res.exception, RuntimeError), (
		f"engine exception escaped to the user: {res.exception!r}"
	)
	# 一次性路径的错误行进 stderr：--json 的 stdout 必须仍是可解析的事件流。
	assert "turn failed" in _ascii(res.stderr or ""), _ascii(
		str(res.stdout)[-200:] + str(res.stderr)[-300:]
	)
	assert "Traceback" not in _ascii(str(res.stderr))
	lines = [ln for ln in (res.stdout or "").splitlines() if ln.strip()]
	assert all(json.loads(ln) for ln in lines), _ascii(str(lines)[:200])


# --------------------------------------------------------------------------
# 6. 已存在的保护（钉住，别在重构里丢掉）
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
	"raw",
	["../../evil", "..\\..\\evil", "a/../../b", "/abs/path", "sess/../x", "  ", "."],
)
def test_chat_session_id_cannot_reach_outside_the_sessions_dir(
	raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""``--session`` 到不了目录外：safe_session_filename 把 ``/`` 等一律换成 ``_``。

	这是「已经安全，原因是清洗」的钉子，不是放行歧义：歧义形态（``victim.`` 与
	``victim`` 同名）仍在**同一用户自己的**会话目录里，读错只可能读到自己；
	破坏性的 ``sessions rm`` 走服务端，那里有固定点 422 守卫。
	"""
	from session.persistence import transcript_path

	sessions = tmp_path / "sessions"
	sessions.mkdir()
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(sessions))
	target = transcript_path(raw)
	assert target.parent == sessions, f"escaped to {target.parent}"
	assert target.name.endswith(".jsonl") and "/" not in target.name


def test_chat_ignores_a_traversal_session_id_without_crashing(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	from msgtypes.events import ResultEvent

	sessions = tmp_path / "sessions"
	sessions.mkdir(exist_ok=True)
	res = _drive_one_shot(monkeypatch, tmp_path, extra=["--session", "../../evil"])
	assert res.exit_code == 0, _ascii(str(res.exception))
	# 真引擎跑了，但目录外没有凭空多出转录文件。
	assert not list(tmp_path.glob("evil.jsonl"))
	assert not list(tmp_path.glob("*.jsonl"))


# --------------------------------------------------------------------------
# 7. GBK / ASCII 控制台：编码只能在真子进程里复现
# --------------------------------------------------------------------------

_SUB_RM_STUB = """
import json, os, sys
home, refusal = sys.argv[1], sys.argv[2]
os.environ["XEYO_HOME"] = home
os.environ["XEYO_SESSIONS_DIR"] = os.path.join(home, "sessions")
import httpx
from cli import sessions_cmd

def _handle(request):
    return httpx.Response(409, json={"detail": json.loads(refusal)})

sessions_cmd.http_api.make_client = lambda url, key="", timeout=60.0: httpx.Client(
    transport=httpx.MockTransport(_handle), base_url=url
)
from cli.main import app
sys.argv = ["xeyo", "sessions", "rm", "sess_x"]
app()
"""


def _run_hostile_console(args: list[str], home: Path) -> subprocess.CompletedProcess:
	"""真子进程 + PYTHONIOENCODING=ascii：测试自己的 stdout 不是 GBK 终端。"""
	return subprocess.run(
		[sys.executable, *args],
		cwd=str(PY_ROOT),
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		timeout=180,
		env={**os.environ, "PYTHONIOENCODING": "ascii", "PYTHONPATH": str(PY_ROOT),
			 "XEYO_HOME": str(home), "XEYO_SESSIONS_DIR": str(home / "sessions")},
	)


def test_config_show_survives_an_ascii_console(tmp_path: Path) -> None:
	"""`config show` 的掩码里有 ``…``，last_cwd 可能是中文：GBK/ASCII 台不许炸。"""
	home = tmp_path / "home"
	home.mkdir(parents=True)
	(home / "config.toml").write_text(
		'api_key = "sk-1234567890"\nlast_cwd = "D:/\u4e34\u65f6\u533a"\n', encoding="utf-8"
	)
	proc = _run_hostile_console(["-m", "cli", "config", "show"], home)
	err = _ascii(proc.stderr[-600:])
	assert "UnicodeEncodeError" not in err, err
	assert "Traceback" not in err, err
	assert proc.returncode == 0, err
	# 不打折：必须真是 U+2026（被替换成 ? 就说明编码守卫没生效）。
	assert "sk-1…90" in proc.stdout, _ascii(proc.stdout[-300:])


def test_servers_chinese_refusal_survives_an_ascii_console(tmp_path: Path) -> None:
	"""删除被服务端用中文拒绝：转述原因不许把 CLI 自己打挂。"""
	home = tmp_path / "home"
	home.mkdir()
	proc = _run_hostile_console(
		["-c", _SUB_RM_STUB, str(home), json.dumps(_CN_REFUSAL)], home
	)
	err = _ascii(proc.stderr[-600:])
	assert "UnicodeEncodeError" not in err, err
	assert "Traceback" not in err, err
	assert proc.returncode == 1, f"rc={proc.returncode} {err}"
	assert "failed via" in _ascii(proc.stdout), _ascii(proc.stdout[-300:])
	assert _CN_REFUSAL in proc.stdout, _ascii(proc.stdout[-300:])


# --------------------------------------------------------------------------- #
# 富文本转义：coord 的两处打印（我自己复现的，不是沿用报告结论）
# --------------------------------------------------------------------------- #


def test_coord_status_survives_brackets_in_the_workspace_path(tmp_path: Path) -> None:
	"""路径里有 ``[`` 是合法目录名，rich 却会把它当标记。

	未转义时有**两种**坏法，都实测过（去掉 escape 复现）：
	- ``[/foo]`` 这类闭合标签 → ``MarkupError``，直接崩；
	- ``[weird]`` 这类看起来像开标签的 → **不崩**，rich 把它当样式吞掉，打印出的
	  路径变成 ``…\\proj`` —— 于是 CLI 报的是一个不存在的目录名。后者更坏：
	  用户看不出任何异常，却拿到了一个被改写的路径。
	``coord run`` 那处在任务已跑完并上交之后才打印，崩或错报都会毁掉一次成功干活。
	"""
	root = tmp_path / "proj[weird]"
	root.mkdir()
	result = runner.invoke(app, ["coord", "status", "--cwd", str(root)])
	err = _ascii(str(result.exception) if result.exception else "")
	assert "MarkupError" not in err, err
	assert "Traceback" not in err, err
	assert result.exit_code == 0, f"rc={result.exit_code} {err} {_ascii(result.output[-300:])}"
	assert "[weird]" in result.output, _ascii(result.output[-300:])


def test_coord_status_json_mode_is_unaffected(tmp_path: Path) -> None:
	"""--json 走 print(json.dumps(...))，本来就不经 rich：别把转义做双份。"""
	root = tmp_path / "proj[ok]"
	root.mkdir()
	result = runner.invoke(app, ["coord", "status", "--cwd", str(root), "--json"])
	assert result.exit_code == 0, _ascii(str(result.exception))
	assert json.loads(result.output)["root"].endswith("proj[ok]")
