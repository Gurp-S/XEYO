"""运行时能力预检契约。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.runtime_capabilities import probe_runtime_capabilities


def test_local_probe_is_side_effect_free_and_has_stable_identity(tmp_path) -> None:  # type: ignore[no-untyped-def]
	first = probe_runtime_capabilities(str(tmp_path), runtime="local")
	second = probe_runtime_capabilities(str(tmp_path), runtime="local")

	assert first.runtime == "local"
	assert first.cwd == str(tmp_path.resolve())
	assert first.writable is True
	assert first.capability_id == second.capability_id
	assert first.to_dict()["checked_at"] != 0


def test_non_local_probe_does_not_claim_host_capabilities(tmp_path) -> None:  # type: ignore[no-untyped-def]
	caps = probe_runtime_capabilities(
		str(tmp_path), runtime="docker", container_id="container-1"
	)

	assert caps.runtime == "docker"
	assert caps.container_id == "container-1"
	assert caps.writable is None
	assert caps.git is None
	assert caps.python is None
	assert caps.node is None
	assert caps.compiler is None
	assert caps.package_manager is None
