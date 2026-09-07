"""离线守卫：侧挂模块在「未升格/回退」时零副作用（不 monkey-patch 主模块）。

验证点（对应「侧面修改、不影响当前代码、随时卸载加载」硬约束）：
- **升格开启（默认，`XEYO_SIDEMOD_PROMOTE` 未设或=1）**：挂钩型 `enabled()==True`、`install()` 会装。
- **回退（`XEYO_SIDEMOD_PROMOTE=0`）**：挂钩型 `enabled()==False`、`install()` 返回 False、主函数未被替换；
  显式 install→uninstall 后恢复原函数（可随时卸载）。纯函数型在回退时 `enabled()==False`。
- 全程不依赖 API key / 模型 / 网络。
"""

from __future__ import annotations

import importlib


# (模块名, 主目标模块名, 挂钩函数名, 专用开关env名)
_HOOKED = [
    ("memory.memindex_sig_shadow", "memory.memindex", "_sync_table", "XEYO_MEMINDEX_SIG_HASH"),
    ("tools.fileio.content_index_cache_shadow", "tools.fileio.content_index", "_build_index", "XEYO_CONTENT_INDEX_CACHE"),
    ("memory.eval_cold_memory_shadow", "memory.search", "search", "XEYO_EVAL_COLD_MEMORY"),
    ("tools.spill_shadow", "tools.spill", "save_text", "XEYO_SPILL_TAIL_HINT"),
    ("prompt.transcript_pointer_shadow", "prompt.pre_llm_inject", "run_pre_llm_inject", "XEYO_C2_TRANSCRIPT_POINTER"),
]

# 已固化开启的侧挂模块（收益明确，不再受专用 env/promote 逐项控制；
# 仅 apply() 的 XEYO_SIDEMOD_PROMOTE=0 全局回退会跳过 install）。行为细节见
# tests/test_rerank_preference.py。
_FIXED = [
    ("memory.rerank_preference_shadow", "memory.search", "search"),
]

_PURE = [
    ("evals.pollution_gate_shadow", "XEYO_EVAL_POLLUTION_GATE"),
    ("evals.blind_audit_shadow", "XEYO_EVAL_BLIND_AUDIT"),
    ("evals.reporting_shadow", "XEYO_EVAL_REPORTING"),
    ("evals.strict_env_shadow", "XEYO_EVAL_STRICT"),
]

_PROMOTE = "XEYO_SIDEMOD_PROMOTE"


def _clear_special_envs(monkeypatch):
    for _m, _t, _h, env in _HOOKED:
        monkeypatch.delenv(env, raising=False)
    for _m, env in _PURE:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv(_PROMOTE, raising=False)


def test_promote_on_by_default(monkeypatch):
    """升格默认开（未设 promote + 未设专用 env）→ 挂钩型 enabled()==True。"""
    _clear_special_envs(monkeypatch)
    assert importlib.import_module("sidecar.policy").sidemod_promote() is True
    for mod_name, _t, _h, _env in _HOOKED:
        mod = importlib.import_module(mod_name)
        assert mod.enabled() is True, f"{mod_name}.enabled() 升格后应默认 True"


def test_promote_off_noop(monkeypatch):
    """回退（`XEYO_SIDEMOD_PROMOTE=0`）→ 挂钩型 enabled()==False、install()==False、主函数未替换。"""
    monkeypatch.setenv(_PROMOTE, "0")
    for mod_name, target, hook, _env in _HOOKED:
        mod = importlib.import_module(mod_name)
        assert mod.enabled() is False, f"{mod_name}.enabled() 回退时应为 False"
        assert mod.install() is False, f"{mod_name}.install() 回退时应返回 False"
        tmod = importlib.import_module(target)
        flag = f"__{mod_name.split('.')[-1].replace('_shadow', '')}_installed"
        assert not getattr(tmod, flag, False), f"{target}.{hook} 被错误安装（回退应无副作用）"


def test_install_then_uninstall_restores(monkeypatch):
    """promote 开启下 install→uninstall，主函数恢复原函数（可随时卸载）。"""
    monkeypatch.setenv(_PROMOTE, "1")
    for mod_name, target, hook, _env in _HOOKED:
        mod = importlib.import_module(mod_name)
        tmod = importlib.import_module(target)
        before = getattr(tmod, hook)
        assert mod.enabled() is True
        assert mod.install() is True, f"{mod_name}.install() 开启时应返回 True"
        assert getattr(tmod, hook) is not before, f"{target}.{hook} 安装后应被替换"
        mod.uninstall()
        assert getattr(tmod, hook) is before, f"{target}.{hook} 卸载后未恢复原函数"
        monkeypatch.delenv(_PROMOTE, raising=False)
        monkeypatch.setenv(_PROMOTE, "1")


def test_pure_modules_no_install_surface(monkeypatch):
    """纯函数型：无 install/uninstall 挂钩面（天然零副作用）；回退时 enabled()==False。"""
    monkeypatch.setenv(_PROMOTE, "0")
    for mod_name, _env in _PURE:
        mod = importlib.import_module(mod_name)
        assert mod.enabled() is False, f"{mod_name}.enabled() 回退时应为 False"
        assert not hasattr(mod, "install"), f"{mod_name} 不应有 install（纯函数）"
        assert not hasattr(mod, "uninstall"), f"{mod_name} 不应有 uninstall（纯函数）"


def test_special_env_overrides_promote(monkeypatch):
    """专用 env 显式则优先：promote 开但 XEYO_MEMINDEX_SIG_HASH=0 → 该模块关。"""
    monkeypatch.setenv(_PROMOTE, "1")
    monkeypatch.setenv("XEYO_MEMINDEX_SIG_HASH", "0")
    mod = importlib.import_module("memory.memindex_sig_shadow")
    assert mod.enabled() is False  # 专用 env=0 覆盖 promote=1


def test_fixed_module_always_on(monkeypatch):
    """固化模块：enabled() 恒 True（env/promote 均不可逐项关），install/uninstall 可用。"""
    monkeypatch.setenv(_PROMOTE, "0")
    for mod_name, target, hook in _FIXED:
        mod = importlib.import_module(mod_name)
        assert mod.enabled() is True, f"{mod_name} 已固化，enabled() 应恒 True"
        tmod = importlib.import_module(target)
        before = getattr(tmod, hook)
        assert mod.install() is True
        assert getattr(tmod, hook) is not before
        mod.uninstall()
        assert getattr(tmod, hook) is before
