"""JSONL 单遍读取：记录和存储事实来自同一次扫描，不截断累计统计。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LedgerRead:
	events: list[dict[str, Any]] = field(default_factory=list)
	raw_lines: int = 0
	blank_lines: int = 0
	bad_lines: int = 0
	store: str = "ok"

	def status(self) -> dict[str, Any]:
		return {
			"store": self.store,
			"store_raw_lines": self.raw_lines if self.store != "unreadable_store" else None,
			"lines_within_read_limit": self.raw_lines if self.store != "unreadable_store" else None,
			"store_unparsable_lines": self.bad_lines,
			"store_blank_lines": self.blank_lines,
			"read_row_limit": None,
			"rows_read": len(self.events),
			"lines_beyond_read_limit": 0,
			"truncated_by_read_limit": False,
		}


def read_ledger(path: Path) -> LedgerRead:
	result = LedgerRead()
	try:
		with path.open("rb") as stream:
			for line in stream:
				result.raw_lines += 1
				if not line.strip():
					result.blank_lines += 1
					continue
				try:
					row = json.loads(line.decode("utf-8"))
				except (UnicodeDecodeError, json.JSONDecodeError):
					result.bad_lines += 1
					continue
				if isinstance(row, dict):
					result.events.append(row)
				else:
					result.bad_lines += 1
	except FileNotFoundError:
		result.store = "missing_store"
	except OSError:
		result.store = "unreadable_store"
	else:
		if not result.events:
			result.store = "empty_store"
	return result
