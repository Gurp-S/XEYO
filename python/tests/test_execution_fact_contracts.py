from pathlib import Path
import pytest


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("XEYO_EXECUTION_FACT_CONTRACTS", "1")


def test_declared_scratch_passes_write_and_bash_predicates(enabled, tmp_path):
    from engine.env_facts import facts
    from permissions.filesystem import protected_metadata_reason
    from permissions.policy import evaluate_policy as evaluate, PermissionDecision
    target = tmp_path / ".xeyo" / "tmp" / "test.txt"
    assert facts(str(tmp_path))["scratch"] == ".xeyo/tmp"
    assert protected_metadata_reason(str(target), cwd=str(tmp_path)) is None
    for tool, inputs in (("Write", {"file_path": str(target), "content": "x"}),
                         ("Bash", {"command": f"Set-Content -LiteralPath '{target}' -Value 'x'"})):
        assert evaluate(tool, inputs, cwd=str(tmp_path)).decision != PermissionDecision.DENY
    for relative in (".xeyo/goals/s.json", ".xeyo/tmp/../goals/s.json", ".xeyo/tmp/.git/config"):
        assert protected_metadata_reason(str(tmp_path / relative), cwd=str(tmp_path)) is not None


def test_validated_edit_after_shell_creation_keeps_cas(enabled, tmp_path):
    from tools.file_edit_tool.file_edit_tool import FileEditTool, EditInput
    from engine.write_store import WriteStore
    target = tmp_path / "created.txt"
    target.write_text("original\n", encoding="utf-8")
    editor = FileEditTool(cwd=str(tmp_path))
    editor.set_write_store(WriteStore(str(tmp_path)))
    inp = EditInput(file_path=str(target), old_string="original", new_string="changed")
    assert editor.validate_input(inp)["result"]
    editor.call(inp)
    assert target.read_text() == "changed\n"
    inp = EditInput(file_path=str(target), old_string="changed", new_string="third")
    assert editor.validate_input(inp)["result"]
    target.write_text("external\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        editor.call(inp)
    assert target.read_text() == "external\n"


def test_mismatch_reports_visible_whitespace_facts(enabled):
    from tools.fileio.edit_contract import mismatch
    output = mismatch("    return value", "def f():\n\treturn value\n")
    assert "nearest_line=2" in output and "\\treturn" in output


def test_receipt_returns_actual_output_and_detects_tampering(enabled, monkeypatch, tmp_path):
    from session import execution_receipt as receipts
    from tools.base_tool import ToolResult
    monkeypatch.setattr(receipts, "trace_path", lambda _: tmp_path / "calls.jsonl")
    receipts.record("s", "call", "Bash", ToolResult(content="successful output"))
    assert receipts.lookup("s", "call")["content"] == "successful output"
    assert receipts.lookup("s", "other") is None
    text = (tmp_path / "calls.jsonl").read_text().replace("successful output", "modified output")
    (tmp_path / "calls.jsonl").write_text(text)
    assert receipts.lookup("s", "call") is None


def test_job_activity_is_observation_not_claim_of_progress(enabled):
    from server.job_registry import JobRegistry
    reg = JobRegistry()
    uid, _ = reg._register(kind="bash", label="test", owner_session_id="s")
    reg._push(uid, "abc")
    row = reg.snapshot_list("s")[0]
    assert row["output_chars"] == 3 and row["last_output_at"] >= row["started_at"]
    assert not row["finished_at"]
    assert reg.snapshot_list("other") == []


def test_composite_delete_proves_every_target_and_ignores_read_suffix(enabled, tmp_path):
    from permissions.bash_targets import targets
    from permissions.policy import evaluate_policy
    from permissions.filesystem import PermissionDecision
    command = "Remove-Item -LiteralPath '.xeyo/tmp/self.ps1'; git status"
    assert targets(command) == (".xeyo/tmp/self.ps1",)
    assert evaluate_policy("Bash", {"command": command}, cwd=str(tmp_path)).decision != PermissionDecision.DENY
    for command in ("Remove-Item -LiteralPath '.xeyo/tmp/self.ps1'; Remove-Item -LiteralPath '../outside.txt'",
                    "Remove-Item -LiteralPath $target; git status",
                    "Remove-Item -LiteralPath '.xeyo/tmp/self.ps1'; Remove-Item -LiteralPath '.git/config'"):
        assert evaluate_policy("Bash", {"command": command}, cwd=str(tmp_path)).decision == PermissionDecision.DENY


def test_denial_explains_category_without_secret_content(enabled):
    from permissions.policy import evaluate_policy
    from engine.execution_facts import denial_text
    inputs = {"command": "Get-Content '.env'"}
    decision = evaluate_policy("Bash", inputs, cwd=".")
    text = denial_text(decision, inputs)
    assert "rule=" in text and "evidence=credential_path" in text
    assert "Get-Content" not in text and ".env" not in text


def test_literal_python_attribute_is_not_a_credential_path(enabled):
    from permissions.bash_policy import bash_secret_read_reason
    command = "Set-Content -LiteralPath 'check.py' -Value @'\nitems = [p.key for p in pins]\n'@"
    assert bash_secret_read_reason(command) is None
    for command in ("Get-Content 'p.key'", "Set-Content -LiteralPath 'p.key' -Value 'x'",
                    "Set-Content -LiteralPath 'check.py' -Value @'\nitems = [p.key for p in pins]\nopen('secret.key').read()\n'@",
                    "Set-Content -LiteralPath 'check.py' -Value @'\ninvalid python p.key \n'@"):
        assert bash_secret_read_reason(command) == "bash_secret_read"


def test_resume_restores_returned_result_instead_of_unknown(enabled, monkeypatch, tmp_path):
    from session import execution_receipt as receipts
    from session.hydrate import _repair_unclosed_tool_uses
    from msgtypes.message import assistant_text_message, ToolUse
    from tools.base_tool import ToolResult
    monkeypatch.setattr(receipts, "trace_path", lambda _: tmp_path / "trace.jsonl")
    monkeypatch.setattr("engine.t_now_notes.current_session_id", lambda: "s")
    receipts.record("s", "c", "Bash", ToolResult(content="actual successful result"))
    output = _repair_unclosed_tool_uses([assistant_text_message("", [ToolUse(id="c", name="Bash", input={"command": "echo x"})])])
    assert output[-1].content[0]["content"] == "actual successful result"
    assert not output[-1].content[0]["is_error"]
    assert output[-1].content[0]["execution"]["complete"] is True
    receipts.record("s", "c", "Bash", ToolResult(content="", status="running", metadata={"execution_complete": False}))
    output = _repair_unclosed_tool_uses([assistant_text_message("", [ToolUse(id="c", name="Bash", input={"command": "echo x"})])])
    assert output[-1].content[0]["execution"]["complete"] is False
