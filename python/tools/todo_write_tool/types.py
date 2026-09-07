from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

TodoStatus = Literal["pending", "in_progress", "completed"]
VALID_STATUSES = frozenset({"pending", "in_progress", "completed"})


@dataclass
class TodoItem:
	content: str
	status: TodoStatus
	active_form: str
	id: str = ""
	#: 可选产物路径（相对工作区）。步骤以"生成文件/产物"收尾时由模型声明；
	#: 进入 sidecar/transcript 恢复链，是引擎侧任务状态注册表的确定性引用，
	#: 供恢复/续跑/收尾引导等消费。UI 白名单（content/status/activeForm）丢弃。
	output: str = ""

	def to_dict(self) -> dict[str, str]:
		return {
			"id": self.id,
			"content": self.content,
			"status": self.status,
			"activeForm": self.active_form,
			"output": self.output,
		}


def todo_item_from_raw(raw: Any) -> TodoItem | None:
	"""解析单个 todo 字典；无效时返回 None。缺 id 时自动生成短 id。"""
	if not isinstance(raw, dict):
		return None
	content = raw.get("content")
	status = raw.get("status")
	active = raw.get("activeForm", raw.get("active_form"))
	if not isinstance(content, str) or not content.strip():
		return None
	if not isinstance(status, str) or status not in VALID_STATUSES:
		return None
	if not isinstance(active, str) or not active.strip():
		return None
	raw_id = raw.get("id")
	item_id = (
		str(raw_id).strip()
		if isinstance(raw_id, str) and raw_id.strip()
		else uuid4().hex[:8]
	)
	raw_output = raw.get("output")
	output = (
		str(raw_output).strip()
		if isinstance(raw_output, str) and raw_output.strip()
		else ""
	)
	return TodoItem(
		content=content.strip(),
		status=status,  # type: ignore[arg-type]
		active_form=active.strip(),
		id=item_id,
		output=output,
	)
