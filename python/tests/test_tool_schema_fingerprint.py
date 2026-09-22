"""工具协议指纹：只反映当前模型可见 tool surface。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry


def test_schema_fingerprint_is_stable_and_snapshot_is_machine_readable() -> None:
	reg = ToolRegistry()
	reg.register(EchoTool())

	one = reg.schema_fingerprint()
	two = reg.schema_fingerprint()
	snapshot = reg.schema_snapshot()

	assert one == two
	assert one.startswith("sha256:")
	assert snapshot["hash"] == one
	assert snapshot["surface_id"] == "custom@1"
	assert snapshot["count"] == 1
	assert snapshot["tool_names"] == ["echo"]
	assert isinstance(snapshot["revision"], int)


def test_registering_a_visible_tool_changes_protocol_fingerprint() -> None:
	reg = ToolRegistry()
	reg.register(EchoTool())
	before = reg.schema_fingerprint()

	class SecondTool(EchoTool):
		name = "second"

		def schema(self):  # type: ignore[no-untyped-def]
			out = super().schema()
			out["name"] = self.name
			return out

	reg.register(SecondTool())

	assert reg.schema_fingerprint() != before
	assert reg.schema_snapshot()["tool_names"] == ["echo", "second"]


def test_surface_identity_is_separate_from_schema_hash() -> None:
	reg = ToolRegistry(tool_surface_id="minimal@1")
	reg.register(EchoTool())

	snapshot = reg.schema_snapshot()

	assert snapshot["surface_id"] == "minimal@1"
	assert snapshot["hash"].startswith("sha256:")
