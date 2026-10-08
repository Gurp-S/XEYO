"""An explicit model request; the following request boundary owns execution."""
from tools.base_tool import ToolResult
from tools.compact_description import DESCRIPTION


class CompactTool:
    name = "Compact"

    @staticmethod
    def is_read_only():
        return True

    @staticmethod
    def is_concurrency_safe():
        return False

    def schema(self):
        return {"name": self.name,
                "description": DESCRIPTION,
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}}

    async def execute(self, input, abort):
        if abort.aborted:
            return ToolResult("Compact cancelled", is_error=True, status="cancelled")
        if input:
            return ToolResult("Invalid arguments: Compact accepts no fields", is_error=True)
        return ToolResult("compaction_request=accepted; execution=pending",
                          metadata={"compaction_request": {"version": 1, "accepted": True}})
