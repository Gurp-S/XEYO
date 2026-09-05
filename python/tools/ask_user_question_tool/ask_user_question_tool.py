"""AskUserQuestionTool — 助手向用户提问（M3 扩展）。

结构化提问：助手给出一句问题 + 可选选项，turn 挂起等待用户作答；
用户作答后被唤醒，返回答案文本（自由输入或选项之一）。

与权限挂起同构：registry.run 检测到本工具命中 ask 门时，不直接执行，
而是创建一条 PendingAsk（见 ask_store），交给 query_loop 等待用户反映，
随后把答案作为 ToolResult 交回模型继续。
"""

from __future__ import annotations

from typing import Any

from engine.abort import AbortController
from tools.ask_user_question_tool.prompt import DESCRIPTION
from tools.base_tool import ToolResult

ASK_USER_TOOL_NAME = "AskUserQuestion"
# 工具输入里保留的请求 id 标记（registry.run 写入，供 resume 阶段取回）。
ASK_REQUEST_ID_KEY = "__ask_request_id"


def _option_label(opt: Any) -> str | None:
	if isinstance(opt, str) and opt.strip():
		return opt.strip()
	if isinstance(opt, dict):
		label = opt.get("label")
		if isinstance(label, str) and label.strip():
			return label.strip()
	return None


def flatten_options(options_raw: Any) -> list[str]:
	"""Normalize options from string[] or {label, description}[]."""
	if not isinstance(options_raw, list):
		return []
	out: list[str] = []
	for o in options_raw:
		label = _option_label(o)
		if label:
			out.append(label)
	return out


def format_questions_payload(raw: dict[str, Any]) -> dict[str, Any]:
	"""Build combined question + flattened options for PendingAsk.

	If questions[] is non-empty: number them into one string and flatten options.
	Else: legacy single question / options / default.
	"""
	questions_raw = raw.get("questions")
	if isinstance(questions_raw, list) and questions_raw:
		parts: list[str] = []
		all_options: list[str] = []
		default: str | None = None
		for i, q in enumerate(questions_raw, start=1):
			if not isinstance(q, dict):
				continue
			text = str(q.get("question") or "").strip()
			if not text:
				continue
			parts.append(f"{i}. {text}")
			opts = flatten_options(q.get("options"))
			for o in opts:
				if o not in all_options:
					all_options.append(o)
			if default is None:
				d = q.get("default")
				if isinstance(d, str) and d.strip():
					default = d.strip()
		combined = "\n".join(parts).strip()
		return {
			"question": combined,
			"options": all_options,
			"default": default,
		}

	question = str(raw.get("question") or "").strip()
	options = flatten_options(raw.get("options"))
	default_raw = raw.get("default")
	default = (
		str(default_raw).strip()
		if isinstance(default_raw, str) and default_raw.strip()
		else (str(default_raw) if default_raw is not None else None)
	)
	return {"question": question, "options": options, "default": default}


class AskUserQuestionTool:
	name = ASK_USER_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict[str, Any]:
		question_item = {
			"type": "object",
			"properties": {
				"question": {
					"type": "string",
					"description": "The question text.",
				},
				"options": {
					"description": (
						"Optional fixed choices as strings or "
						"{label, description} objects."
					),
					"oneOf": [
						{"type": "array", "items": {"type": "string"}},
						{
							"type": "array",
							"items": {
								"type": "object",
								"properties": {
									"label": {"type": "string"},
									"description": {"type": "string"},
								},
								"required": ["label"],
							},
						},
					],
				},
				"multiSelect": {
					"type": "boolean",
					"description": "Allow multiple selections (UI hint).",
				},
				"default": {
					"type": "string",
					"description": "Optional default for this question.",
				},
			},
			"required": ["question"],
		}
		return {
			"name": self.name,
			"description": DESCRIPTION,
			"input_schema": {
				"type": "object",
				"properties": {
					"question": {
						"type": "string",
						"description": "The question to ask the user (legacy single).",
					},
					"options": {
						"type": "array",
						"items": {"type": "string"},
						"description": "Optional fixed choices. If given, prefer them; "
						"otherwise the user may freely type an answer.",
					},
					"default": {
						"type": "string",
						"description": "Optional default to prefill / fall back to.",
					},
					"questions": {
						"type": "array",
						"description": (
							"Optional multi-question form. When non-empty, "
							"numbered into one combined question for the pause UI."
						),
						"items": question_item,
					},
				},
				"required": [],
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		# 正常流程由 registry.run 挂起并在 resume 后取回答案；这里仅在
		# 直接调用（如测试/脚手架）时兜底：返回需要等待回答的提示。
		abort.raise_if_aborted()
		payload = format_questions_payload(input if isinstance(input, dict) else {})
		question = str(payload.get("question") or "").strip()
		return ToolResult(
			content=(
				f"[AskUserQuestion requires a pending answer] {question}"
				if question
				else "[AskUserQuestion requires a question]"
			),
			is_error=not bool(question),
		)
