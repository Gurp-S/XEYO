"""状态权威清单契约。"""

from engine.state_authority import authority_manifest


def test_events_and_ui_are_derived_not_state_owners() -> None:
	manifest = authority_manifest()
	assert manifest["conversation"]["owner"] == "MessageStore"
	assert manifest["process"]["owner"] == "JobRegistry/ProcessManager"
	assert manifest["events"]["derived"] is True
	assert manifest["ui"]["derived"] is True


def test_manifest_is_a_copy() -> None:
	first = authority_manifest()
	first["conversation"]["owner"] = "caller"
	assert authority_manifest()["conversation"]["owner"] == "MessageStore"
