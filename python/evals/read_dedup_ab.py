"""零 API、真实 FileReadTool：范围等价收益与折叠后正文可用性合同。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from tools.file_read_tool.file_read_tool import FileReadTool, ReadInput, ReadOutput
from tools.fileio.read_visibility import sync_read_visibility, view_digest
from tools.fileio.text import get_mtime_ms


def run(root: Path, *, repaired: bool, alternating: bool) -> dict:
	root = root.resolve()
	root.mkdir(parents=True, exist_ok=True)
	path = root / "contract.txt"
	path.write_text("API contract: preserve existing arguments and error signatures.\n" * 100, encoding="utf-8")
	tool = FileReadTool(cwd=str(root))
	registry = SimpleNamespace(_tools={"Read": tool})
	visible: list[dict] = []
	full_digest = ""
	sent_chars = failed_visibility = full_reads = 0
	for shot in range(100):
		if not alternating and shot % 10 == 0:
			visible = []
		request = ReadInput(file_path=str(path), limit=2000 if alternating and shot % 2 else None)
		if repaired:
			sync_read_visibility(registry, visible)
			result = tool.call(request)
		else:
			# 精确复现修复前去重条件；磁盘读取仍由生产工具执行。
			entry = tool._read_state.get(str(path))
			if entry and entry.offset == 1 and entry.limit == request.limit and entry.timestamp == get_mtime_ms(str(path)):
				result = ReadOutput(type="file_unchanged", file_path=str(path))
			else:
				if entry:
					entry.view_visible = False
				result = tool.call(request)
				tool._read_state.get(str(path)).limit = request.limit
		body = tool.map_tool_result_to_content(result)
		if result.type == "text":
			full_reads += 1
			full_digest = view_digest(body)
		visible.append({"role": "tool", "content": body})
		available = {view_digest(row["content"]) for row in visible}
		failed_visibility += int(full_digest not in available)
		sent_chars += len(body)
	return {"requests": 100, "full_reads": full_reads, "result_characters": sent_chars,
	        "requested_body_unavailable": failed_visibility}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--output", type=Path, required=True)
	args = parser.parse_args()
	result = {"scope": "controlled real Read calls; result characters, not vendor cost or task success"}
	for name, alternating in (("equivalent_ranges", True), ("folded_visibility", False)):
		result[name] = {arm: run(args.output.parent / "read-dedup-workspace" / name / arm,
		                        repaired=arm == "repaired", alternating=alternating)
		                for arm in ("baseline", "repaired")}
	assert result["equivalent_ranges"]["repaired"]["result_characters"] < result["equivalent_ranges"]["baseline"]["result_characters"]
	assert result["folded_visibility"]["repaired"]["requested_body_unavailable"] == 0
	args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
	print(json.dumps(result))


if __name__ == "__main__":
	main()
