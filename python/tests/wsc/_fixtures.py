"""WSC 测试用的合成会话构造器（不依赖真实 ~/.xeyo/sessions）。

构造的会话刻意包含设计文档里点名的三类结构：失败分支、结构依赖、过期状态。
"""

from __future__ import annotations

from typing import Any

CONSTRAINT = "不能修改 API 协议，必须保持 v1 兼容"
SRC = "src/auth.ts"


def msg_user(text: str) -> dict[str, Any]:
	return {"role": "user", "content": text}


def msg_asst_text(text: str) -> dict[str, Any]:
	return {"role": "assistant", "content": text}


def msg_asst_use(uid: str, name: str, inp: dict[str, Any]) -> dict[str, Any]:
	return {
		"role": "assistant",
		"content": [{"type": "tool_use", "id": uid, "name": name, "input": inp}],
	}


def msg_tool(uid: str, name: str, content: str, *, is_error: bool = False) -> dict[str, Any]:
	return {
		"role": "user",
		"content": [
			{
				"type": "tool_result",
				"tool_use_id": uid,
				"content": content,
				"is_error": is_error,
			}
		],
		"name": name,
	}


def _blob(tag: str, n_lines: int = 40) -> str:
	return tag + "\n" + "\n".join(f"line {i}: filler {'x' * 40}" for i in range(n_lines))


def synth_session(
	*,
	turns: int = 10,
	error_turn: int = 4,
	include_constraint: bool = True,
	include_todo: bool = True,
	user_every: int = 0,
) -> list[dict[str, Any]]:
	"""合成一条具备失败分支 / 重复读取 / 写后过期 / 未解决错误的会话。

``user_every`` > 0 时每 N 轮插一条后继用户消息（默认 0 = 只有开局那一条）。
它用来构造「区域内有用户原话」的形态——规则 1 的信息空洞只在那种形态下暴露。
	"""
	if turns < 2:
		raise ValueError("turns must be >= 2")
	error_turn = max(0, min(int(error_turn), turns - 1))
	msgs: list[dict[str, Any]] = []
	msgs.append(msg_user("修复登录超时" + (f"。{CONSTRAINT}" if include_constraint else "")))

	for t in range(turns):
		uid_r = f"r{t}"
		msgs.append(msg_asst_use(uid_r, "Read", {"path": SRC, "offset": 1, "limit": 60}))
		msgs.append(msg_tool(uid_r, "Read", _blob(f"// {SRC} v{t}")))

		if include_todo and t == 1:
			msgs.append(
				msg_asst_use(
					"todo1",
					"TodoWrite",
					{
						"todos": [
							{"content": "定位超时来源", "status": "completed"},
							{"content": "修改 proxy 超时配置", "status": "in_progress"},
							{"content": "补齐超时回归测试", "status": "pending"},
						]
					},
				)
			)
			msgs.append(msg_tool("todo1", "TodoWrite", "ok"))

		if t == error_turn:
			uid_e = f"e{t}"
			# 失败命令刻意带文件路径：err 边依赖「失败现场」与后续动作共享 refs
			msgs.append(
				msg_asst_use(uid_e, "Bash", {"command": f"npm test -- {SRC}"})
			)
			msgs.append(
				msg_tool(
					uid_e,
					"Bash",
					"FAILED test_login_timeout\nAssertionError: expected 1000 got 3000\nPROXY_OVERRIDE",
					is_error=True,
				)
			)
			# 失败分支：尝试改超时时间（结果无错，但结论是无效方案）
			uid_w = f"w{t}"
			msgs.append(
				msg_asst_use(uid_w, "Edit", {"path": SRC, "old_string": "timeout = 3000", "new_string": "timeout = 1000"})
			)
			msgs.append(msg_tool(uid_w, "Edit", "edited"))

		if t == turns - 1:
			msgs.append(
				msg_asst_use("bash1", "Bash", {"command": "grep -rn proxy_conf src/"})
			)
			msgs.append(msg_tool("bash1", "Bash", "src/auth.ts:120: proxy_conf = load()"))

		msgs.append(msg_asst_text(f"第 {t} 轮：已读取 {SRC}，继续分析。"))

		if user_every and (t + 1) % user_every == 0 and t != turns - 1:
			msgs.append(msg_user(f"接着看第 {t} 轮的结论：请只改配置，不要动测试。"))

	return msgs


def synth_api_session(*, turns: int = 10, **kw) -> list[dict[str, Any]]:
	"""与 synth_session 相同，但把尾部留足（供 region_end 切分用）。"""
	return synth_session(turns=turns, **kw)
