# -*- coding: utf-8 -*-
"""P1: catalog.py bench 工具面 = 原生面 - 评测环境里没有对象的工具。
P2: query_engine.build_default_engine 增加 thinking / reasoning_effort 接线。"""
import sys
from pathlib import Path

NL = "\n"

# ---------- P1 ----------
p = Path("python/tools/catalog.py")
s = p.read_text(encoding="utf-8")
OLD = """		excluded = {
			"Skill", "Agent", "Memory", "AskUserQuestion",
			"Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit",
			"Screenshot", "SendToWeChat", "XeyoUI", "JournalQuery",
			"Diagnostics", "Git", "WebFetch", "WebSearch",
		}"""
NEW = """		# 2026-09-14 收窄：原先把 Read/Write/Edit/Glob/Grep + Git/WebFetch/
		# WebSearch/Diagnostics/Agent/Skill/Memory/JournalQuery 一起裁掉，等于把
		# 产品原生工具面砍到只剩 bash。取证：harbor 自带适配器里 claude-code
		# 默认 permission-mode=bypassPermissions 且不传 allowed/disallowed tools，
		# codex 默认 reasoning_effort=high —— 富工具面 scaffold 一律用**产品原生
		# 工具面**参赛；只有 terminus-2（tmux 键击）/ mini-swe-agent（单 bash 工具）
		# 这类 scaffold 天生 bash-only，那是它们的形态，不是评测口径。
		# 仍排除的只剩「在 headless 评测里没有作用对象」的工具：人机交互工具会把
		# agent 卡在等一个不存在的用户上，宿主 GUI / 微信通道在此进程里没有接口。
		# 另外 JournalQuery（会话自查询）不得被评测分支排除 —— 见红线
		# 「会话自查询工具必须无条件注册」。
		excluded = {
			"AskUserQuestion",
			"Screenshot", "SendToWeChat", "XeyoUI",
		}"""
assert s.count(OLD) == 1, f"P1 anchor: {s.count(OLD)}"
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8", newline=NL)
print("P1 ok: catalog.py bench excluded 18 -> 4")

# ---------- P2 ----------
q = Path("python/engine/query_engine.py")
t = q.read_text(encoding="utf-8")

OLD_SIG = "    base_url: str | None = None,\n    initial_messages: list[Message] | None = None,\n) -> QueryEngine:"
NEW_SIG = ("    base_url: str | None = None,\n"
           "    initial_messages: list[Message] | None = None,\n"
           "    thinking: str = \"disabled\",\n"
           "    reasoning_effort: str = \"\",\n"
           ") -> QueryEngine:")
assert t.count(OLD_SIG) == 1, f"P2 sig anchor: {t.count(OLD_SIG)}"
t = t.replace(OLD_SIG, NEW_SIG, 1)

OLD_CLI = """        model_client = OpenAICompatClient(
            api_key=key,
            base_url=url,
            model=resolved_model_name,
            provider=backend if backend in PROVIDER_PRESETS else "openai",
            session_id=session_id or "",
        )"""
NEW_CLI = """        model_client = OpenAICompatClient(
            api_key=key,
            base_url=url,
            model=resolved_model_name,
            provider=backend if backend in PROVIDER_PRESETS else "openai",
            # 思考态与档位：默认值与 OpenAICompatClient 自身默认一致（deepseek
            # 提供方下显式发 thinking:disabled），故既有调用方行为零变化。
            # 走 deepseek 提供方的调用方现在能显式开思考/抬档位——此前
            # build_default_engine 不传这两个参数，档位无法表达。
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            session_id=session_id or "",
        )"""
assert t.count(OLD_CLI) == 1, f"P2 client anchor: {t.count(OLD_CLI)}"
t = t.replace(OLD_CLI, NEW_CLI, 1)
q.write_text(t, encoding="utf-8", newline=NL)
print("P2 ok: build_default_engine(+thinking, +reasoning_effort) -> OpenAICompatClient")
