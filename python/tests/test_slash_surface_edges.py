"""``POST /v1/slash`` 的路由边缘回归（最后一个未加固的 HTTP 入口）。

每条测试对应一个先用 TestClient 实测复现、后修掉的缺陷：

1. 相对 ``workspace``（``..`` / ``%2e%2e``）按**服务端进程 cwd**解析：
   ``/ls`` 直接把调用者选的目录（服务端 cwd 之上）列进响应——未注册项目
   之外的内容泄露。现在 422。
2. 含控制字符的 ``workspace``（``x\\x00y``）在 ``Path.resolve()`` 处以
   ``ValueError`` 逃出路由 → 500。现在 422。
3. sanitizer 别名 ``session_id``（``"victim."`` 与 ``"victim"`` 落到同一个
   磁盘文件名）直达 ``RewindHotpath``：``/revert`` 既读到 victim 的回溯事件
   （跨会话读取），又把新事件写进 victim 的事件日志（跨会话写入）。现在 422。
4. ``arg`` 原样进 ``git`` argv（``/diff <rev>``）→ 选项注入
   ``--output=<任意路径>`` 让服务端在越狱路径上写文件。现在 422。

按设计**不**收紧的字段（本文件用测试把它们钉成"保持现状"）：
``name`` 只做 ``slash.registry`` 的字典查表（查不到即 unknown，无副作用）；
``provider`` / ``base_url`` / ``model`` 是模型端点选择，``base_url`` 的 SSRF
口径已在 ``server.deps._resolve_base_url`` 集中处理。

约定：只写 OS 临时目录（XEYO_HOME / XEYO_DATA_DIR / XEYO_SESSIONS_DIR 全量
重定向 + ``monkeypatch.chdir`` 挪走服务端 cwd），断言不打印中文（GBK 控制台）。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
	home = tmp_path / "home"
	data = tmp_path / "data"
	sessions = tmp_path / "sessions"
	for d in (home, data, sessions):
		d.mkdir(parents=True, exist_ok=True)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.setenv("XEYO_DATA_DIR", str(data))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(sessions))
	# 服务端进程 cwd 挪进临时目录：相对 workspace 的解析基准由此可控，
	# 万一逃逸写发生也只会落在 OS 临时目录里。
	proc = tmp_path / "proc"
	proc.mkdir()
	(proc / "CANARY_DIR_LEAK.txt").write_text("outside any registered project", encoding="utf-8")
	server_cwd = proc / "cwd"
	server_cwd.mkdir()
	monkeypatch.chdir(server_cwd)
	ws = tmp_path / "ws"
	(ws / ".xeyo").mkdir(parents=True)
	return {
		"tmp": tmp_path,
		"home": home,
		"data": data,
		"sessions": sessions,
		"proc": proc,
		"ws": ws,
	}


def _app():
	from server.app import app

	return app


def _ascii_only(text: str) -> str:
	return text.encode("ascii", "backslashreplace").decode("ascii")


def _post(client: TestClient, **body: object):
	return client.post("/v1/slash", json=body)


def _seed_victim(sessions: Path) -> tuple[Path, Path]:
	"""真实的 victim 会话：transcript + 一条已完成的 rewind 事件。"""
	transcript = sessions / "victim.jsonl"
	rows = [
		{"id": "m1", "role": "user", "content": "first", "ts": 1.0},
		{"id": "m2", "role": "assistant", "content": "second", "ts": 2.0},
	]
	transcript.write_text(
		"\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
	)
	sdir = sessions / "victim"
	sdir.mkdir(parents=True, exist_ok=True)
	events = sdir / "rewind_events.jsonl"
	events.write_text(
		json.dumps(
			{
				"rewind_id": "rw_victim_1",
				"session_id": "victim",
				"mode": "restore",
				"ts": 3.0,
				"target_message_id": "m2",
				"checkpoint_id": "",
				"status": "failed",
			}
		)
		+ "\n",
		encoding="utf-8",
	)
	return transcript, events


def _mk_git_repo(dir_path: Path) -> Path:
	"""一个有未提交改动的小型 git 仓库（供 ``/diff`` 的 argv 注入探针使用）。"""
	dir_path.mkdir(parents=True, exist_ok=True)
	env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t"}
	env["GIT_COMMITTER_NAME"] = "t"
	env["GIT_COMMITTER_EMAIL"] = "t@t"

	def _git(*args: str) -> None:
		subprocess.run(
			["git", *args],
			cwd=str(dir_path),
			check=True,
			capture_output=True,
			timeout=60,
			env=env,
		)

	_git("init", "-q")
	(dir_path / "f.txt").write_text("a\n", encoding="utf-8")
	_git("add", "f.txt")
	_git("commit", "-qm", "init")
	(dir_path / "f.txt").write_text("b\n", encoding="utf-8")
	return dir_path


# --------------------------------------------------------------------------- #
# 1 + 2. workspace：相对路径按服务端 cwd 解析 / 控制字符 500 逃逸
# --------------------------------------------------------------------------- #


def test_relative_workspace_does_not_list_outside_directory(
	sandbox: dict[str, Path],
) -> None:
	with TestClient(_app()) as client:
		for raw in ("..", ".", "a/b", "%2e%2e"):
			r = _post(client, name="ls", arg="", workspace=raw)
			assert r.status_code == 422, (
				raw,
				r.status_code,
				_ascii_only(r.text)[:160],
			)
			assert r.json()["error"]["type"] == "invalid_request"
			assert "CANARY_DIR_LEAK" not in _ascii_only(r.text)
		# 绝对且存在的目录仍然可用（回归保护：不是把 workspace 一禁了之）
		ok = _post(client, name="ls", arg="", workspace=str(sandbox["ws"]))
		assert ok.status_code == 200, _ascii_only(ok.text)[:160]


def test_control_char_workspace_no_longer_escapes_as_500(
	sandbox: dict[str, Path],
) -> None:
	with TestClient(_app()) as client:
		for raw in ("x\x00y", "a\nb", "a\x1ab"):
			r = _post(client, name="ls", arg="", workspace=raw)
			assert r.status_code == 422, (
				_ascii_only(raw),
				r.status_code,
				_ascii_only(r.text)[:160],
			)


def test_blank_workspace_still_falls_back_to_registered_cwd(
	sandbox: dict[str, Path],
) -> None:
	"""空白 = 回退已登记 cwd（与其它路由一致，不许改成 422）。"""
	with TestClient(_app()) as client:
		for raw in ("", "   ", None):
			r = _post(client, name="ls", arg="", workspace=raw)
			assert r.status_code == 200, (repr(raw), r.status_code, _ascii_only(r.text)[:160])


# --------------------------------------------------------------------------- #
# 3. session_id：sanitizer 别名直达 RewindHotpath
# --------------------------------------------------------------------------- #


def test_aliasing_session_id_cannot_read_victims_rewind_events(
	sandbox: dict[str, Path],
) -> None:
	_seed_victim(sandbox["sessions"])
	ws = str(sandbox["ws"])
	with TestClient(_app()) as client:
		for raw in ("victim.", ".victim", "victim ", "vi:ctim"):
			r = _post(client, name="revert", arg="", session_id=raw, workspace=ws)
			assert r.status_code == 422, (
				_ascii_only(raw),
				r.status_code,
				_ascii_only(r.text)[:160],
			)
			# 越权读取的证据不能出现在响应里
			assert "rw_victim_1" not in r.text
		# 真身份仍然可用（守卫不是黑名单）
		good = _post(client, name="revert", arg="", session_id="victim", workspace=ws)
		assert good.status_code == 200, _ascii_only(good.text)[:160]
		assert "rw_victim_1" in good.text


def test_aliasing_session_id_cannot_write_into_victims_event_log(
	sandbox: dict[str, Path],
) -> None:
	_, events = _seed_victim(sandbox["sessions"])
	before = events.read_text(encoding="utf-8")
	ws = str(sandbox["ws"])
	with TestClient(_app()) as client:
		r = _post(
			client,
			name="revert",
			arg="rw_victim_1 confirm",
			session_id="victim.",
			workspace=ws,
		)
		assert r.status_code == 422, (r.status_code, _ascii_only(r.text)[:160])
	after = events.read_text(encoding="utf-8")
	assert after == before, "alias 会话 id 把事件写进了 victim 的日志"


# --------------------------------------------------------------------------- #
# 4. arg：原样进 git argv → 选项注入 = 任意路径写
# --------------------------------------------------------------------------- #


def test_diff_arg_cannot_inject_git_options(sandbox: dict[str, Path]) -> None:
	pytest.importorskip("shutil")
	import shutil as _shutil

	if _shutil.which("git") is None:
		pytest.skip("git not available")
	repo = _mk_git_repo(sandbox["tmp"] / "repo")
	target = sandbox["tmp"] / "PWNED.txt"
	with TestClient(_app()) as client:
		r = _post(
			client,
			name="diff",
			arg=f"--output={target}",
			workspace=str(repo),
		)
		wrote = target.is_file()
		assert r.status_code == 422, (
			r.status_code,
			f"wrote={wrote}",
			_ascii_only(r.text)[:160],
		)
	assert not wrote, "git 以调用者给的绝对路径写了文件（argv 选项注入未挡）"
	assert not target.exists(), "PWNED 文件仍在"


def test_diff_arg_cannot_carry_git_options_after_a_valid_revision(
	sandbox: dict[str, Path],
) -> None:
	"""只查首 token 的写法在这里失效：``HEAD`` 合法，选项夹在后面照样写文件。

	实测（不经路由，直接在带改动的仓库里跑）：
	``git diff --stat HEAD --output=<绝对路径>`` 退出码 0 且**确实落盘** ——
	git 在 rev/pathspec 之后仍认这个选项。所以判据必须看全部 token。
	"""
	import shutil as _shutil

	if _shutil.which("git") is None:
		pytest.skip("git not available")
	repo = _mk_git_repo(sandbox["tmp"] / "repo2")
	target = sandbox["tmp"] / "PWNED2.txt"
	with TestClient(_app()) as client:
		r = _post(
			client,
			name="diff",
			arg=f"HEAD --output={target}",
			workspace=str(repo),
		)
		assert r.status_code == 422, (
			r.status_code,
			f"wrote={target.is_file()}",
			_ascii_only(r.text)[:160],
		)
	assert not target.exists(), "合法 rev 打头夹带 --output 仍然写到了任意路径"


def test_diff_still_accepts_a_normal_revision(sandbox: dict[str, Path]) -> None:
	import shutil as _shutil

	if _shutil.which("git") is None:
		pytest.skip("git not available")
	repo = _mk_git_repo(sandbox["tmp"] / "repo2")
	with TestClient(_app()) as client:
		ok = _post(client, name="diff", arg="", workspace=str(repo))
		assert ok.status_code == 200, _ascii_only(ok.text)[:160]
		head = _post(client, name="diff", arg="HEAD", workspace=str(repo))
		assert head.status_code == 200, _ascii_only(head.text)[:160]


# --------------------------------------------------------------------------- #
# 5. 谓词本身 + 明确不动的字段
# --------------------------------------------------------------------------- #


def test_shared_predicates_are_the_ones_in_use() -> None:
	from server.routers.extensions import require_workspace_arg
	from server.routers.sessions import require_session_id

	assert require_workspace_arg(None) == ""
	assert require_workspace_arg("   ") == ""
	assert require_session_id("victim") == "victim"
	for bad in ("..", "rel/ws", "x\x00y"):
		with pytest.raises(Exception) as exc:
			require_workspace_arg(bad)
		assert getattr(exc.value, "status_code", None) == 422
	for bad in ("victim.", ".victim", "vi:ctim", " victim", "", "   ", "a/b"):
		with pytest.raises(Exception) as exc:
			require_session_id(bad)
		assert getattr(exc.value, "status_code", None) == 422


def test_registry_lookup_and_model_endpoint_fields_are_unchanged(
	sandbox: dict[str, Path],
) -> None:
	"""按设计保留：``name`` 是字典查表，provider/base_url 是端点选择。

	这条测试的作用是**钉住**"不要顺手收紧这些字段"：它们都不进文件系统，
	base_url 的 SSRF 口径集中在 ``server.deps._resolve_base_url``。
	"""
	with TestClient(_app()) as client:
		unknown = _post(client, name="no-such-command", arg="")
		assert unknown.status_code == 200, _ascii_only(unknown.text)[:160]
		assert unknown.json()["kind"] == "unknown"
		# 名字里带别名形态也只是「查不到」，不产生任何状态
		aliasy = _post(client, name="victim.", arg="")
		assert aliasy.status_code == 200
		assert aliasy.json()["handled"] is False
		model_choice = _post(
			client,
			name="status",
			provider="bogus",
			base_url="https://api.openai.com/v1",
			model="whatever",
			workspace=str(sandbox["ws"]),
		)
		assert model_choice.status_code == 200, _ascii_only(model_choice.text)[:160]
		# base_url 的越权口径由 server.deps._resolve_base_url 集中把关（既有机制，
		# 不在本次边缘加固范围内）：私网地址在这里就已经是 403。
		private = _post(
			client,
			name="status",
			provider="bogus",
			base_url="http://127.0.0.1:1/v1",
			workspace=str(sandbox["ws"]),
		)
		assert private.status_code == 403, _ascii_only(private.text)[:160]
		assert "private_ip" in private.text
