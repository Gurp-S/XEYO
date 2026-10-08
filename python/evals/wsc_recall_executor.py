"""Product read-only retrieval tools scoped to an isolated evaluation root."""
import asyncio
from pathlib import Path

from engine.abort import AbortController
from engine.execution_facts import tool_receipt
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.grep_tool.grep_tool import GrepTool


class RecallExecutor:
    def __init__(self, root, surface="read"):
        self.root = Path(root).resolve()
        self.tools = {"Read": FileReadTool(cwd=str(self.root))}
        if surface == "read_search":
            self.tools["Grep"] = GrepTool(cwd=str(self.root))
        elif surface != "read":
            raise ValueError("unknown_recall_surface")

    def schemas(self):
        return [tool.schema() for tool in self.tools.values()]

    def execute(self, name, arguments):
        if name not in self.tools:
            return {"is_error": True, "content": "Permission denied: recall_read_only"}
        key = "file_path" if name == "Read" else "path"
        target = (self.root / str(arguments.get(key, "."))).resolve()
        if not target.is_relative_to(self.root):
            return {"is_error": True, "content": "Permission denied: fixture_path_scope"}
        result = asyncio.run(self.tools[name].execute(arguments, AbortController()))
        return {"is_error": result.is_error, "content": result.content, "execution": tool_receipt(result)}
