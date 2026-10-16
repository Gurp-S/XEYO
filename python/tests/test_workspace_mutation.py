from __future__ import annotations

import pytest

from engine.workspace_lock import WorkspaceLock
from engine.workspace_mutation import WorkspaceMutationBusy, hold_workspace_mutation


def test_workspace_mutation_uses_the_shared_workspace_lease(tmp_path):
	workspace = tmp_path / "workspace"
	workspace.mkdir()
	owner = WorkspaceLock(workspace, owner="rewind")
	owner.acquire()
	try:
		with pytest.raises(WorkspaceMutationBusy):
			with hold_workspace_mutation(workspace, owner="chat-write", timeout=0):
				pytest.fail("mutation entered while another workspace lease was held")
	finally:
		owner.release()

	with hold_workspace_mutation(workspace, owner="chat-write", timeout=0):
		assert True
