"""T31 跨入口会话与模式 SSOT 测试。

覆盖：
① 模式 durable 化 —— WorkingSnapshot durable 记录 + resume 重放 + 请求体投影覆盖。
② 会话 id 服务端签发 —— POST /v1/sessions 出服务端 id；复用不换；不再客户端自造 UUID。
③ workspace SSOT —— 客户端只发 workspace id → 服务端解析权威路径；已 pinned 会话不被
   客户端 workspace 覆写（服务端说了算）。

尽量用 mock / 轻量对象避免整引擎 spin（不起真实模型调用）。
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from memory.working import (
    WorkingSnapshot,
    apply_modes,
    flush,
    hydrate,
    resolve_modes,
)


# --------------------------------------------------------------------------- #
# ① 模式 durable 化
# --------------------------------------------------------------------------- #


def test_mode_durable_roundtrip(tmp_path: Path, monkeypatch) -> None:
    """set ask/plan/output_compact → flush → hydrate(resume) → 模式重建。"""
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    snap = WorkingSnapshot(session_id="s1")
    apply_modes(
        snap,
        {
            "agent_mode": "plan",
            "output_compact": True,
            "output_mode": "ultra",
            "code_compact": True,
            "code_mode": "lite",
        },
    )
    flush("s1", snap)

    resumed = hydrate("s1")
    assert resumed.agent_mode == "plan"
    assert resumed.output_compact is True
    assert resumed.output_mode == "ultra"
    assert resumed.code_compact is True
    assert resumed.code_mode == "lite"


def test_mode_durable_default_when_absent(tmp_path: Path, monkeypatch) -> None:
    """无模式记录的会话 resume 时必须回退默认（agent/off），不 crash。"""
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    snap = WorkingSnapshot(session_id="s2")
    flush("s2", snap)
    resumed = hydrate("s2")
    assert resumed.agent_mode == "agent"
    assert resumed.output_compact is False
    assert resumed.code_compact is False
    assert resumed.output_mode == ""


def test_resolve_modes_durable_authoritative_on_resume() -> None:
    """resume（请求体 None）以 durable 为准；显式请求体才覆盖（投影）。"""
    snap = WorkingSnapshot(
        session_id="s3",
        agent_mode="ask",
        output_compact=True,
        output_mode="full",
        code_compact=False,
        code_mode="",
    )
    # 客户端未发模式 → durable 胜出
    eff = resolve_modes(
        snap,
        agent_mode=None,
        output_compact=None,
        output_mode=None,
        code_compact=None,
        code_mode=None,
    )
    assert eff["agent_mode"] == "ask"
    assert eff["output_compact"] is True
    assert eff["output_mode"] == "full"
    assert eff["code_compact"] is False
    # 显式覆盖：请求体仍是投影，显式值胜出；未设字段继续用 durable
    eff2 = resolve_modes(snap, agent_mode="agent", output_compact=False, code_mode="ultra")
    assert eff2["agent_mode"] == "agent"
    assert eff2["output_compact"] is False
    assert eff2["output_mode"] == "full"
    assert eff2["code_mode"] == "ultra"


def test_effective_request_modes_overlay() -> None:
    """chat.py 的 `_effective_request_modes` 模拟 resume 路径（engine working 为 durable）。"""
    from server.routers.chat import ChatCompletionRequest, _effective_request_modes

    snap = WorkingSnapshot(
        session_id="s4",
        agent_mode="plan",
        output_compact=True,
        output_mode="ultra",
        code_compact=False,
        code_mode="",
    )
    engine = SimpleNamespace(
        session_id="s4",
        _session=SimpleNamespace(working=snap),
    )

    # resume：client 未发模式（None）→ durable plan 生效
    body = ChatCompletionRequest(model="m", messages=[], agent_mode=None, output_compact=None)
    eff = _effective_request_modes(engine, body)
    assert eff["agent_mode"] == "plan"
    assert eff["output_compact"] is True
    assert eff["output_mode"] == "ultra"

    # 显式覆盖非默认：写回 durable
    body2 = ChatCompletionRequest(
        model="m",
        messages=[],
        agent_mode="ask",
        output_compact=False,
        output_mode="lite",
        code_compact=True,
        code_mode="lite",
    )
    eff2 = _effective_request_modes(engine, body2)
    assert eff2["agent_mode"] == "ask"
    assert eff2["output_compact"] is False
    assert eff2["output_mode"] == "lite"
    assert eff2["code_compact"] is True
    # durable 记录已被覆盖（供后续 resume 重放）
    assert snap.agent_mode == "ask"
    assert snap.output_compact is False
    assert snap.code_compact is True


# --------------------------------------------------------------------------- #
# ② 会话 id 服务端签发
# --------------------------------------------------------------------------- #


def test_create_session_server_issued(tmp_path: Path, monkeypatch) -> None:
    """POST /v1/sessions 返回服务端签发 id + 服务端解析的真实工作区路径。"""
    from server.routers import sessions as sessions_module
    from server.session_pool import SessionPool

    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    monkeypatch.setattr(sessions_module, "_pool", pool)

    res = sessions_module.create_session(
        sessions_module.NewSessionRequest(workspace=str(tmp_path))
    )
    assert res["ok"] is True
    sid = res["session_id"]
    assert sid and sid.startswith("xeyo-")
    assert os.path.realpath(res["cwd"]) == os.path.realpath(str(tmp_path))


def test_server_session_id_stable_on_reuse(tmp_path: Path, monkeypatch) -> None:
    """服务端签发的 id 在 engine 复用时不换（tui 不再每轮自造 UUID）。"""
    from server.routers import sessions as sessions_module
    from server.session_pool import ModelConfig, SessionPool

    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    monkeypatch.setattr(sessions_module, "_pool", pool)

    res = sessions_module.create_session(
        sessions_module.NewSessionRequest(workspace=str(tmp_path))
    )
    sid = res["session_id"]
    cfg = ModelConfig(provider="deepseek", api_key="k", base_url="http://127.0.0.1:1", model="m")
    pool.get_or_create(sid, cfg, cwd=str(tmp_path))
    eng = pool.get_or_create(sid, cfg)  # 复用：不换 id
    assert eng.session_id == sid


# --------------------------------------------------------------------------- #
# ③ workspace SSOT（服务端权威）
# --------------------------------------------------------------------------- #


def test_workspace_ssot_server_resolves_id(tmp_path: Path, monkeypatch) -> None:
    """客户端只发 workspace id → 服务端解析真实路径；空 → 服务端默认工作区。"""
    from memory.memdir import workspace_id
    from server.session_pool import SessionPool

    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    ws = tmp_path / "proj"
    ws.mkdir()
    pool.set_cwd(str(ws))  # 登记 id → path（服务端权威）
    wid = workspace_id(str(ws))

    # id → 路径（服务端解析）
    assert pool.resolve_workspace(wid) == os.path.realpath(str(ws))
    # 空 → 服务端默认工作区（ui_cwd）
    assert pool.resolve_workspace("") == os.path.realpath(str(ws))
    # 直接发路径 → 一并解析并登记 id
    other = tmp_path / "other"
    other.mkdir()
    assert pool.resolve_workspace(str(other)) == os.path.realpath(str(other))
    assert pool.resolve_workspace(workspace_id(str(other))) == os.path.realpath(str(other))


def test_pinned_session_not_overridden_by_client_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    """已 pinned cwd 的会话不被客户端 workspace 覆写（不冲突、不回退到 _ui_cwd）。"""
    from server.routers import chat as chat_module
    from server.session_pool import ModelConfig, SessionPool

    pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
    monkeypatch.setattr(chat_module, "_pool", pool)

    ws = tmp_path / "pinned"
    ws.mkdir()
    cfg = ModelConfig(provider="deepseek", api_key="k", base_url="http://127.0.0.1:1", model="m")
    pool.get_or_create("sess", cfg, cwd=str(ws))
    assert pool.session_cwd("sess") == os.path.realpath(str(ws))

    # 客户端想用一个不同的 workspace → 服务端忽略（返回 None，走 pinned）
    body = chat_module.ChatCompletionRequest(
        model="m", messages=[], workspace=str(tmp_path / "other")
    )
    assert chat_module._workspace_for("sess", body) is None

    # 复用时以 None workspace → pool 用 pinned cwd，不回退到 _ui_cwd（tmp_path）
    eng = pool.get_or_create("sess", cfg, cwd=None)
    assert os.path.realpath(str(eng.config["cwd"])) == os.path.realpath(str(ws))
    # 服务端权威：既不是客户端想改的 other，也不是 ui_cwd 默认
    assert os.path.realpath(str(eng.config["cwd"])) != os.path.realpath(
        str(tmp_path)
    )
