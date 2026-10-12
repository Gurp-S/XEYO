"""Offline friction probes. Candidates live only here; production is untouched.

Run from python/: py -3.11 -m evals.harness_friction_audit --out <report.json>
A = actual digest projection and Edit persistence. B = existing full projection
plus a strict Python compile gate in an evaluation-only subclass. No LLM calls.
This is a mechanism comparison, not evidence of task-level success.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch


@contextlib.contextmanager
def environment(values):
    before = dict(os.environ)
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        os.environ.clear()
        os.environ.update(before)


def edit_probe(root, case, candidate, with_store):
    from engine.write_store import WriteStore
    from prompt.tool_result_diff_digest import apply_tool_result_digest
    from tools.file_edit_tool.file_edit_tool import EditInput, FileEditTool

    class CompileGateEdit(FileEditTool):
        # Evaluation-only: strict validation of the exact normalized candidate.
        # No bytecode write, subprocess, execution of source, or rollback.
        def _persist(self, full, content, *, encoding, line_endings):
            if Path(full).suffix.lower() == ".py":
                compile(content, full, "exec", dont_inherit=True)
            return super()._persist(full, content, encoding=encoding, line_endings=line_endings)

    before, old, new, external = case
    target = root / "example.py"
    target.write_text(before, encoding="utf-8")
    tool = (CompileGateEdit if candidate else FileEditTool)(cwd=str(root))
    if with_store:
        tool.set_write_store(WriteStore(str(root)))
    inp = EditInput(str(target), old, new)
    validation = tool.validate_input(inp)
    if not validation.get("result"):
        raise RuntimeError(validation)
    if external is not None:
        target.write_text(external, encoding="utf-8")
    snapshot = target.read_bytes()
    error = None
    raw = ""
    try:
        output = tool.call(inp)
        raw = tool.map_tool_result_to_content(output)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raw = error
    messages = [{"role": "tool", "name": "Edit", "content": [
        {"type": "tool_result", "tool_use_id": "audit-edit", "content": raw}]}]
    saved = copy.deepcopy(messages)
    with environment({"XEYO_TOOL_RESULT_DIFF": "full" if candidate else "digest"}):
        projected = apply_tool_result_digest(messages)
        twice = apply_tool_result_digest(projected)
    visible = projected[0]["content"][0]["content"]
    after = target.read_text(encoding="utf-8")
    try:
        compile(after, str(target), "exec", dont_inherit=True)
        syntax_valid = True
    except SyntaxError:
        syntax_valid = False
    return {
        "accepted": error is None, "error": error,
        "disk_unchanged": target.read_bytes() == snapshot,
        "syntax_valid_after": syntax_valid,
        "model_diff_visible": "```diff" in visible,
        "raw_chars": len(raw), "model_chars": len(visible),
        "projection_preserves_transcript": messages == saved,
        "projection_idempotent": projected == twice,
        "after": after, "model_result": visible,
    }


def flag_probe():
    from engine import execution_facts, env_facts, env_switches
    from tools import meta
    from tools.file_read_tool.file_read_tool import read_structure_hint_enabled
    from tools.grep_tool.grep_tool import pagination_facts_enabled, symbol_ranges_enabled
    from tools.bash_tool.bash_tool import error_origin_enabled
    predicates = {
        execution_facts.ENV: execution_facts.enabled,
        execution_facts.ENV_COMPLETENESS: execution_facts.completeness_facts_enabled,
        execution_facts.ENV_SCRATCH: execution_facts.scratch_writable_enabled,
        env_facts.ENV_EXTRA: env_facts.extra_facts_enabled,
        env_facts.ENV_SYNTAX: env_facts.syntax_fact_enabled,
        meta.ENV_DESC_FACTS: meta.tool_desc_facts_enabled,
        "XEYO_READ_STRUCTURE_HINT": read_structure_hint_enabled,
        "XEYO_GREP_PAGINATION_FACTS": pagination_facts_enabled,
        "XEYO_GREP_SYMBOL_RANGES": symbol_ranges_enabled,
        "XEYO_BASH_ERROR_ORIGIN": error_origin_enabled,
    }
    registered = {switch.name for switch in env_switches.SWITCHES}
    rows = []
    for name, predicate in predicates.items():
        effective = predicate()
        with environment({name: None}):
            default = predicate()
        with environment({name: "0"}):
            off = predicate()
        with environment({name: "1"}):
            on = predicate()
        rows.append({"name": name, "effective": effective, "default": default,
                     "explicit_0": off, "explicit_1": on,
                     "registered": name in registered})
    return rows


def verdict_probe():
    from evals.changedetect import __main__ as cli
    from evals.changedetect import surface
    # Actual current renderer, fake artifacts to isolate presentation from goldens.
    with patch.object(surface, "collect", return_value=[]), \
         patch.object(surface, "compare", return_value=[]), \
         patch.object(surface, "render_index", return_value="artifact-1\nartifact-2\n"):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = cli.cmd_surface_check(argparse.Namespace(max_show=8, strict=True))
    original = stream.getvalue()
    lines = original.splitlines()
    verdict = next(line for line in lines if line.startswith("[L0]"))
    candidate = "\n".join([verdict] + [line for line in lines if line != verdict]) + "\n"
    return {"fixture": "two artifacts; unchanged surface", "exit_code": code,
            "A": original, "B": candidate,
            "A_verdict_line": lines.index(verdict) + 1, "B_verdict_line": 1,
            "same_lines": sorted(original.splitlines()) == sorted(candidate.splitlines())}


def loaded_code_probe(root):
    # Demonstrates why a fresh git hash/version cannot identify loaded code.
    import hashlib
    import marshal
    import types
    target = root / "runtime_fixture.py"
    target.write_text("def value():\n    return 1\n", encoding="utf-8")
    module = types.ModuleType("audit_runtime_fixture")
    exec(compile(target.read_text(), str(target), "exec"), module.__dict__)
    loaded_hash = hashlib.sha256(marshal.dumps(module.value.__code__)).hexdigest()
    target.write_text("def value():\n    return 2\n", encoding="utf-8")
    return {"fixture": True, "loaded_value": module.value(),
            "disk_value": 2, "loaded_code_hash": loaded_hash,
            "hash_stable_after_disk_change": loaded_hash == hashlib.sha256(
                marshal.dumps(module.value.__code__)).hexdigest(),
            "scope": "one loaded function, not a complete backend build identity"}


def presence_probe(root):
    from engine.session_presence import PresenceState, FILE_OWNERSHIP_TTL_SEC, MAX_OWNED_PATHS
    state = PresenceState()
    for index in range(MAX_OWNED_PATHS + 1):
        state.note_write(str(root), "audit-session", str(root / f"file{index}.py"))
    entry = next(iter(state.by_root.values()))["audit-session"]
    bounded = len(entry.owned_files)
    latest = max(entry.owned_files.values())
    entry.prune_owned(now=latest + FILE_OWNERSHIP_TTL_SEC + 1)
    return {"writes": MAX_OWNED_PATHS + 1, "retained_before_ttl": bounded,
            "retained_after_ttl": len(entry.owned_files),
            "not_in_session_ledger_does_not_prove_external_author": True}


def environment_probe(root):
    from engine import env_facts
    # Isolate cache lifetime and permission changes from host probing.
    previous = dict(env_facts._FACTS_CACHE)
    try:
        env_facts._FACTS_CACHE.clear()
        with patch.object(env_facts, "collect", return_value={"shell": "fixture-shell"}) as collect, \
             patch("engine.execution_facts.writable", return_value=False):
            env_facts.facts(str(root))
            env_facts.facts(str(root))
            calls = collect.call_count
        env_facts._FACTS_CACHE[str(root)] = {"scratch": ".xeyo/tmp", "writable": str(root)}
        with patch("engine.execution_facts.writable", return_value=False):
            narrowed = env_facts.facts(str(root))
        return {"fixture": "two calls, then cached writable scope narrowed",
                "collect_calls_for_two_facts_requests": calls,
                "scope_denied_but_cached_scratch_visible": "scratch" in narrowed,
                "scope_denied_but_writable_visible": "writable" in narrowed}
    finally:
        env_facts._FACTS_CACHE.clear()
        env_facts._FACTS_CACHE.update(previous)


def run():
    cases = {
        "legal_semantic_deletion": ('message = (\n    "ERROR: "\n    "details"\n)\n',
                                    '    "ERROR: "\n', "", None),
        "syntax_error": ("value = 1\n", "1", "(", None),
        "compile_only_error": ("value = 1\n", "value = 1", "return 1", None),
        "undefined_name": ("value = 1\n", "1", "MISSING_CONSTANT", None),
        "external_write_after_validate": ("value = 1\n", "1", "2", "value = 99\n"),
    }
    repo = Path(__file__).resolve().parents[2]
    report = {"scope": "offline mechanisms; no model tasks; no production integration",
              "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
              "cases": {}, "flags": flag_probe(), "verdict": verdict_probe()}
    inputs = (
        "python/tools/file_edit_tool/file_edit_tool.py",
        "python/engine/write_store.py", "python/prompt/tool_result_diff_digest.py",
        "python/engine/env_facts.py", "python/engine/env_switches.py",
        "python/engine/session_presence.py", "python/engine/execution_facts.py",
        "python/evals/changedetect/__main__.py", "python/server/portfile.py",
        "scripts/baseline_run.ps1",
    )
    report["source_sha256"] = {
        name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in inputs}
    with tempfile.TemporaryDirectory(prefix="xeyo-friction-ab-") as temp:
        root = Path(temp)
        isolated = {"XEYO_HOME": str(root / "home"), "XEYO_JOURNAL_DIR": str(root / "journal"),
                    "XEYO_METRICS_DIR": str(root / "metrics"), "XEYO_EXECUTION_FACT_CONTRACTS": "1"}
        with environment(isolated):
            for name, case in cases.items():
                for store in (False, True):
                    key = f"{name}/{'store' if store else 'direct'}"
                    report["cases"][key] = {}
                    for label, candidate in (("A", False), ("B", True)):
                        workspace = root / name / str(store) / label
                        workspace.mkdir(parents=True)
                        report["cases"][key][label] = edit_probe(workspace, case, candidate, store)
            report["runtime_fixture"] = loaded_code_probe(root)
            report["presence"] = presence_probe(root)
            report["environment"] = environment_probe(root)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {args.out.resolve()}; paired cases: {len(report['cases'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
