"""Literal writes retain all path boundaries; no policy bypass for redirects."""
import pytest
from permissions.bash_targets import targets
from permissions.policy import evaluate_policy, set_permission_mode
from permissions.filesystem import PermissionDecision


@pytest.mark.parametrize("command, expected", [
    ("mkdir dir; echo hi > dir/x.txt", ("dir", "dir/x.txt")),
    ("echo hi>>'space file.txt'", ("space file.txt",)),
    ("echo hi >one.txt 2>>two.txt", ("one.txt", "two.txt")),
    ("echo 'literal > content' > result.txt", ("result.txt",)),
    ("npm run build >> build.log", ("build.log",)),
    ("Remove-Item -LiteralPath 'old.txt'; git status", ("old.txt",)),
    ("New-Item -ItemType Directory foo", ("foo",)),
    ("Set-Content -Path inside.txt -Value hi", ("inside.txt",)),
])
def test_literal_targets(command, expected):
    assert targets(command) == expected


@pytest.mark.parametrize("command", [
    "echo hi > $target", 'echo "$(touch outside)" > in.txt',
    'echo hi > "out""side.txt"', "echo hi > safe.txt; cd ..; echo hi > outside.txt",
    "cd ..; echo hi > file.txt", "echo hi > out.txt; unknown-mutator",
    "echo hi > *.txt", "echo hi > file.txt < input.txt", "echo hi >",
    "New-Item -Path safe -Name ../../outside", "Remove-Item -LiteralPath safe ../outside",
    "New-Item -UnknownOption foo safe",
])
def test_ambiguous_commands_have_no_target_proof(command):
    assert targets(command) is None


@pytest.mark.parametrize("decision", ["deny", "ask"])
def test_redirects_keep_configured_tightening_rules(tmp_path, decision):
    import json
    from permissions.bash_policy import clear_bash_rules_cache, bash_readonly_allow
    (tmp_path / ".xeyo").mkdir()
    (tmp_path / ".xeyo" / "bash_rules.json").write_text(json.dumps({"rules": [
        {"name": "echo-control", "program": "echo", "prefix": [], "decision": decision}
    ]}))
    clear_bash_rules_cache()
    set_permission_mode("risk")
    for command in ("echo hi > safe.txt", "mkdir inside; echo hi > safe.txt"):
        verdict = evaluate_policy("Bash", {"command": command}, cwd=str(tmp_path), allowed_paths=[str(tmp_path)])
        assert verdict.decision.value == decision
        assert not bash_readonly_allow(command, cwd=str(tmp_path))


def test_redirect_chain_validates_every_target_and_respects_confirmation(tmp_path):
    set_permission_mode("risk")
    def check(command):
        return evaluate_policy("Bash", {"command": command}, cwd=str(tmp_path), allowed_paths=[str(tmp_path)])
    assert check("mkdir folder; echo hi > folder/x.txt").decision == PermissionDecision.ALLOW
    for command in ("echo hi > ok.txt 2> ../outside.txt", "mkdir folder; echo hi > .git/config",
                    "echo hi > ok.txt; echo hi > .env", "echo hi > .xeyo-policy.json"):
        assert check(command).decision == PermissionDecision.DENY
    set_permission_mode("always")
    assert check("echo hi > local.txt").decision == PermissionDecision.ASK


@pytest.mark.asyncio
async def test_actual_bash_write_with_quoted_spaces_invalidates_glob(tmp_path):
    from engine.abort import AbortController
    from tools.bash_tool.bash_tool import BashTool
    from tools.glob_tool.glob_tool import GlobTool
    set_permission_mode("risk")
    glob = GlobTool(cwd=str(tmp_path))
    await glob.execute({"pattern": "**/*"}, AbortController())
    destination = tmp_path / "space folder"
    command = f"mkdir '{destination.as_posix()}'; echo hi > '{(destination / 'x.txt').as_posix()}'"
    result = await BashTool(cwd=str(tmp_path)).execute({"command": command}, AbortController())
    assert not result.is_error, result.content
    assert (destination / "x.txt").is_file()
    listed = await glob.execute({"pattern": "**/*"}, AbortController())
    assert not listed.metadata.get("cached")
    assert "space folder/" in listed.content
