"""provider=local 的 SSRF 放宽范围。

`_resolve_base_url` 里这条分支原来是**整体跳过**校验：只要本地模型被授权，
`base_url` 无论什么都直接返回。于是"开了本地推理"这张门票同时放行
`file://`、云元数据 IP（169.254.169.254）、reserved/multicast、以及 DNS 失败的
主机名 —— 而这条分支真正需要的只是"环回 / 内网的一台 llama-server"。

这里的用例钉住放宽的**边界**：环回和 RFC1918 放行，其余一律 403。
判据放在 `tools.web_common.is_local_inference_url`（URL 策略的唯一权威），
不在 deps 里另写一份 IP 分类。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import server.deps as deps
import tools.web_common as web_common


@pytest.fixture()
def local_gate_on(monkeypatch: pytest.MonkeyPatch):
	monkeypatch.setattr(deps, "local_model_allowed", lambda: True)


def _resolve(base_url: str) -> str | None:
	try:
		return deps._resolve_base_url("local", base_url)
	except HTTPException as exc:
		assert exc.status_code == 403, exc
		return None


# --------------------------------------------------------------------------- #
# 该放行的：本机 / 内网的推理服务
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
	"url",
	[
		"http://127.0.0.1:8080/v1",
		"http://localhost:8080/v1",
		"http://192.168.1.20:8080/v1",
		"http://10.0.0.7:8080/v1",
		"http://[::1]:8080/v1",
	],
)
def test_loopback_and_private_are_accepted(local_gate_on, url: str) -> None:
	assert _resolve(url) == url.rstrip("/")


# --------------------------------------------------------------------------- #
# 不该放行的：这些以前都被这条分支整体放过
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
	"url",
	[
		# 云元数据端点
		"http://169.254.169.254/latest/meta-data/",
		# 非 http scheme
		"file:///c:/windows/win.ini",
		"ftp://127.0.0.1/model.gguf",
		# reserved / multicast / unspecified
		"http://240.0.0.1:8080/v1",
		"http://224.0.0.1:8080/v1",
	],
)
def test_metadata_and_non_http_are_denied(local_gate_on, url: str) -> None:
	assert _resolve(url) is None, f"provider=local 不该放行 {url}"


def test_dns_failure_is_denied_not_forgiven(
	local_gate_on, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""解析不出来＝拒绝。以前这条分支不做解析，所以连 dns_failed 都放过。"""

	def _fail(_host, _port):
		raise OSError("mocked dns failure")

	monkeypatch.setattr(web_common.socket, "getaddrinfo", _fail)
	assert _resolve("http://inference.internal:8080/v1") is None


def test_hostname_resolving_to_metadata_is_denied(
	local_gate_on, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""主机名解析到元数据 IP 也不行（DNS rebinding 的同一条判据）。"""

	def _to_meta(_host, _port):
		return [(2, 1, 6, "", ("169.254.169.254", 80))]

	monkeypatch.setattr(web_common.socket, "getaddrinfo", _to_meta)
	assert _resolve("http://evil.example:8080/v1") is None


def test_public_host_is_denied_for_local_provider(
	local_gate_on, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""provider=local 是"本地推理"，公网地址不属于它的语义范围。

	真要连远端的 openai 兼容端点，走 provider/设置里保存过的 base_url
	（`_is_user_configured_base_url` 那条更早的口径），不靠本地档放过。
	"""
	monkeypatch.setattr(
		web_common.socket,
		"getaddrinfo",
		lambda _h, _p: [(2, 1, 6, "", ("93.184.216.34", 80))],
	)
	assert _resolve("http://remote.example.com:8080/v1") is None


def test_gate_off_keeps_the_strict_guard(monkeypatch: pytest.MonkeyPatch) -> None:
	"""没开本地模型时，环回地址照旧被挡 —— 这条分支不是通用后门。"""
	monkeypatch.setattr(deps, "local_model_allowed", lambda: False)
	with pytest.raises(HTTPException) as exc:
		deps._resolve_base_url("local", "http://127.0.0.1:8080/v1")
	assert exc.value.status_code == 403
