from __future__ import annotations

from dataclasses import asdict, replace
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import ast
import json
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wsc import (WSC, Store, Generated, HostReceipt, HostRejection, Limits, Selection,
                 Understanding, Usage, WSCError)
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.callback import CallbackHost
from wsc.contracts import digest, encode
from wsc.generation import JsonCommandGenerator
from wsc.plugin import Plugin


def message(role, text, **extra):
    return {"type": "message", "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}], **extra}


class DurableTestHost:
    """An offline fault-injection host, never a production Codex receipt."""
    def __init__(self, path, core, items):
        self.path, self.core = path, core
        self.lose_reply = False
        self.bad_reply = False
        self.max_items = 10000
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, data TEXT)")
            db.execute("INSERT OR IGNORE INTO state VALUES (1, ?)", (encode({"items": items, "effects": 0}),))

    def state(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            return json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])

    def install(self, package):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM receipts WHERE id=?", (package["operation_id"],)).fetchone()
            if row:
                return HostReceipt(**json.loads(row[0]))
            status = self.core.status()
            with self.core.store.connect() as state:
                control = json.loads(state.execute("SELECT value FROM meta WHERE key='control_epoch'").fetchone()[0])
            if status["generation"] != package["binding"]["generation"] or control != package["binding"]["control_epoch"]:
                raise ValueError("test_host_binding_changed")
            if len(package["items"]) > self.max_items:
                raise ValueError("test_host_capacity_rejected")
            state = json.loads(db.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
            state["items"] = package["items"] + state["items"][package["through"]:]
            state["effects"] += 1
            receipt = HostReceipt(package["operation_id"], package["package_digest"],
                                  package["binding"]["session_id"], package["binding"]["workspace"],
                                  package["next_generation"], package["binding"]["control_epoch"],
                                  package["through"], "offline_test_host", True)
            db.execute("UPDATE state SET data=? WHERE id=1", (encode(state),))
            db.execute("INSERT INTO receipts VALUES (?,?)", (receipt.operation_id, encode(asdict(receipt))))
        if self.lose_reply:
            raise TimeoutError("reply_lost_after_commit")
        return replace(receipt, generation=999) if self.bad_reply else receipt

    def lookup(self, operation_id):
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT data FROM receipts WHERE id=?", (operation_id,)).fetchone()
            return HostReceipt(**json.loads(row[0])) if row else None


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wsc-tests-")
        self.root = Path(self.temp.name)
        self.denied = set()
        self.core = self.reopen()
        self.adapter = CodexCheckpointAdapter()
        self.items = [message("user", "目标 A；保留约束。"),
                      {"type": "function_call", "call_id": "c1", "name": "read", "arguments": "{}"},
                      {"type": "function_call_output", "call_id": "c1", "output": "old observation"},
                      {"type": "reasoning", "encrypted_content": "opaque-private-value"},
                      message("assistant", "Explicit diagnosis", phase="final_answer")]
        self.batch = self.adapter.import_items(self.items, thread_id="native-thread")
        self.ids = self.core.ingest(self.batch)
        self.core.presented("offline-request", (self.ids[2],), receiver="offline_test_model_input")
        self.host = DurableTestHost(self.root / "host.db", self.core, self.items)

    def reopen(self):
        return WSC(Store(self.root / "wsc.db", session_id="session", workspace=str(self.root)),
                   access=lambda session, source, action: (source, action) not in self.denied)

    def test_presented_many_records_the_same_receipts_as_single_calls(self):
        root = Path(self.temp.name)
        core = WSC(Store(root / "batch.db", session_id="batch", workspace=str(root)),
                   access=lambda *_: True)
        ids = core.ingest(self.batch)
        core.presented_many([("request-a", (ids[2],), "batch_receiver")])
        core.presented_many([("request-a", (ids[2],), "batch_receiver")])
        with self.assertRaisesRegex(WSCError, "presentation_identity_conflict"):
            core.presented_many([("request-a", (ids[2],), "other_receiver")])
        core.capture()

    def tearDown(self):
        self.temp.cleanup()

    def view(self, **kwargs):
        return self.core.prepare(self.core.capture(), Selection(new_understandings=(
            Understanding("Diagnosis tied to historical observation", "diagnosis", (self.ids[2],),
                          scope={"time": "historical", "current_applicability": "unknown"}),)),
            producer="offline_test_model", **kwargs)

    def staged(self):
        return self.core.stage(self.view(), directory=self.root / "exports", adapter=self.adapter)

    def test_identity_and_atomic_ingestion(self):
        self.assertEqual(self.ids, self.core.ingest(self.batch))
        with self.assertRaisesRegex(WSCError, "source_identity_conflict"):
            self.core.ingest([replace(self.batch[0], text="modified")])
        before = self.core.status()["source_count"]
        invalid = self.adapter.import_items([message("assistant", "new"),
                    {"type": "function_call_output", "call_id": "missing", "output": "no pair"}],
                    thread_id="other")
        with self.assertRaisesRegex(WSCError, "unpaired_result"):
            self.core.ingest(invalid)
        self.assertEqual(before, self.core.status()["source_count"])

    def test_pairing_and_presentation_are_distinct(self):
        with self.assertRaisesRegex(WSCError, "pending_tool_results"):
            self.core.capture(cut=2)
        with self.core.store.transaction() as db:
            db.execute("DELETE FROM presentations")
        with self.assertRaisesRegex(WSCError, "result_presentation_unknown"):
            self.core.capture()
        self.core.presented("p", (self.ids[2],), receiver="offline_test_model_input")
        self.assertEqual(5, self.core.capture().cut)

    def test_roles_opaque_and_tail_are_preserved(self):
        snap = self.core.capture()
        material = self.core.material(snap)
        self.assertNotIn("opaque-private-value", encode(material))
        tail = message("assistant", "late response", phase="final_answer")
        self.core.ingest(self.adapter.import_items([tail], thread_id="native-thread", start_ordinal=5))
        view = self.core.prepare(snap, Selection(source_ids=(self.ids[2],)), producer="test")
        op = self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)
        p = self.core.package(op)
        self.assertEqual(self.items[0], p["items"][0])
        self.assertEqual(tail, p["items"][-1])
        self.assertFalse(any(x["type"] == "function_call_output" for x in p["items"]))
        self.assertEqual(self.items[3], json.loads(Path(p["evidence"][self.ids[3]]["file_path"]).read_text()))
        self.assertNotIn("opaque-private-value", encode(p["items"]))
        with self.assertRaisesRegex(WSCError, "opaque_source_public_read_unavailable"):
            self.core.read(self.ids[3])

    def test_new_user_invalidates_candidate_without_changing_source(self):
        snap = self.core.capture()
        self.core.ingest(self.adapter.import_items([message("user", "Changed authorization")],
                                                  thread_id="native-thread", start_ordinal=5))
        with self.assertRaisesRegex(WSCError, "control_changed"):
            self.core.prepare(snap, Selection(), producer="test")
        self.assertEqual(0, self.core.status()["cursor"])
        self.assertEqual(6, self.core.status()["source_count"])

    def test_export_is_not_install_and_failed_reply_reconciles_once(self):
        op = self.staged()
        self.assertEqual(0, self.core.status()["cursor"])
        self.host.lose_reply = True
        with self.assertRaises(TimeoutError):
            self.core.install(op, self.host)
        self.assertEqual(0, self.core.status()["cursor"])
        self.assertEqual(1, self.host.state()["effects"])
        with self.assertRaisesRegex(WSCError, "reconciliation"):
            self.core.install(op, self.host)
        with self.assertRaisesRegex(WSCError, "publication_outcome_unknown"):
            self.core.discard(op)
        core = self.reopen()
        core.reconcile(op, self.host)
        core.install(op, self.host)
        self.assertEqual(5, core.status()["cursor"])
        self.assertEqual(1, self.host.state()["effects"])

    def test_invalid_receipt_never_folds(self):
        op = self.staged()
        self.host.bad_reply = True
        with self.assertRaisesRegex(WSCError, "host_receipt_binding_mismatch"):
            self.core.install(op, self.host)
        self.assertEqual(0, self.core.status()["cursor"])
        self.core.reconcile(op, self.host)
        self.assertEqual(1, self.core.status()["generation"])

    def test_unknown_lookup_never_means_unexecuted(self):
        op = self.staged()
        host = CallbackHost(commit=lambda p: (_ for _ in ()).throw(TimeoutError()), lookup=lambda key: None)
        with self.assertRaises(TimeoutError):
            self.core.install(op, host)
        with self.assertRaisesRegex(WSCError, "host_outcome_unknown"):
            self.reopen().reconcile(op, host)
        self.assertEqual(0, self.core.status()["cursor"])

    def test_terminal_host_rejection_allows_new_candidate(self):
        op = self.staged()
        package = self.core.package(op)
        rejection = HostRejection(op, package["package_digest"], "session", str(self.root.resolve()),
                                  "host_capacity_unavailable", "offline_host")
        host = CallbackHost(commit=lambda p: rejection, lookup=lambda key: rejection)
        self.assertEqual("host_capacity_unavailable", self.core.install(op, host)["reason"])
        self.assertEqual("rejected", self.core.status()["operations"][-1]["state"])
        self.assertEqual(0, self.core.status()["cursor"])
        self.assertTrue(self.staged())

    def test_host_preserves_events_appended_after_export(self):
        op = self.staged()
        tail = message("assistant", "response after checkpoint export")
        self.core.ingest(self.adapter.import_items([tail], thread_id="tail"))
        with closing(sqlite3.connect(self.host.path)) as db, db:
            state = self.host.state()
            state["items"].append(tail)
            db.execute("UPDATE state SET data=? WHERE id=1", (encode(state),))
        self.core.install(op, self.host)
        self.assertEqual(tail, self.host.state()["items"][-1])
        self.assertEqual(5, self.core.status()["cursor"])
        self.assertEqual(6, self.core.status()["source_count"])

    def test_preparing_crash_can_be_abandoned_without_install(self):
        # A process died after reserving an operation but before exporting files.
        with self.core.store.transaction() as db:
            db.execute("INSERT INTO operations(id,kind,state,data) VALUES (?,?,?,?)",
                       ("interrupted-export", "publish", "preparing", "{}"))
        self.reopen().discard("interrupted-export")
        self.assertTrue(self.staged())

    def test_stale_ready_can_be_cancelled_without_host_execution(self):
        op = self.staged()
        self.core.ingest(self.adapter.import_items([message("user", "new constraint")], thread_id="new"))
        with self.assertRaisesRegex(WSCError, "control_changed"):
            self.core.install(op, self.host)
        self.core.discard(op)
        self.staged()
        self.assertEqual(0, self.host.state()["effects"])

    def test_evidence_tamper_and_revocation_prevent_install(self):
        op = self.staged()
        self.denied.add((self.ids[2], "export"))
        with self.assertRaisesRegex(WSCError, "Permission denied"):
            self.core.install(op, self.host)
        self.denied.clear()
        p = self.core.package(op)
        Path(p["evidence"][self.ids[2]]["file_path"]).write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(WSCError, "exported_source_changed"):
            self.core.install(op, self.host)
        self.assertEqual(0, self.host.state()["effects"])

    def test_partial_reads_have_distinct_hash_and_current_access(self):
        full = self.core.read(self.ids[0])
        part = self.core.read(self.ids[0], offset=1, limit=7)
        self.assertEqual(full["content"][1:8], part["content"])
        self.assertFalse(part["complete"])
        self.assertEqual(sha256(part["content"]).hexdigest(), part["read_sha256"])
        self.assertEqual(full["object_sha256"], part["object_sha256"])
        self.denied.add((self.ids[0], "read"))
        with self.assertRaisesRegex(WSCError, "Permission denied"):
            self.core.read(self.ids[0])

    def test_revisions_are_cas_and_old_views_cannot_publish(self):
        first = self.core.remember(Understanding("Hypothesis", "hypothesis", (self.ids[2],)), producer="model")
        snap = self.core.capture()
        second = self.core.remember(Understanding("Counterevidence", "diagnosis", (self.ids[2],),
                                                  id=first["id"], expected_revision=1), producer="model")
        self.assertEqual(first["ref"], second["previous"])
        with self.assertRaisesRegex(WSCError, "understanding_revision_conflict"):
            self.core.remember(Understanding("stale edit", "diagnosis", id=first["id"], expected_revision=1), producer="model")
        with self.assertRaisesRegex(WSCError, "understanding_changed"):
            self.core.prepare(snap, Selection(understanding_refs=(first["ref"],)), producer="model")
        self.assertEqual(2, len(self.core.material(self.core.capture())["understandings"]))

    def test_disabled_plugin_is_identity_without_initialization(self):
        def factory():
            self.fail("disabled factory invoked")
        plugin = Plugin(factory=factory)
        context = object()
        self.assertIs(context, plugin.observe(context, events=self.batch))
        observer = Plugin(mode="observe", factory=lambda: self.core)
        self.assertIs(context, observer.observe(context, events=self.batch))
        with self.assertRaisesRegex(WSCError, "component_not_active"):
            observer.install("anything", self.host)

    def test_detach_has_readable_handoff_and_freezes_generation(self):
        self.core.install(self.staged(), self.host)
        plugin = Plugin(mode="active", factory=lambda: self.core)
        _ = plugin.core
        with self.assertRaisesRegex(WSCError, "handoff_not_confirmed"):
            plugin.disable()
        op = self.core.stage_detach(directory=self.root / "handoff", adapter=self.adapter)
        with self.assertRaisesRegex(WSCError, "component_switching"):
            self.core.remember(Understanding("new", "hypothesis"), producer="test")
        package = self.core.package(op)
        self.core.install(op, self.host)
        plugin.disable()
        self.assertEqual("off", plugin.mode)
        self.assertEqual("detached", self.core.status()["mode"])
        for source in package["evidence"].values():
            self.assertTrue(Path(source["file_path"]).is_file())
        self.assertTrue(self.reopen().read(self.ids[0])["complete"])
        with self.assertRaisesRegex(WSCError, "component_detached"):
            self.core.ingest(self.batch)

    def test_pending_call_stays_unfolded_and_late_result_remains(self):
        snap = self.core.capture()
        tail = [{"type": "function_call", "call_id": "late", "name": "read", "arguments": "{}"}]
        self.core.ingest(self.adapter.import_items(tail, thread_id="late"))
        view = self.core.prepare(snap, Selection(), producer="test")
        with self.assertRaisesRegex(WSCError, "checkpoint_requires_idle_tools"):
            self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)
        tail.append({"type": "function_call_output", "call_id": "late", "output": "new result"})
        self.core.ingest(self.adapter.import_items(tail[1:], thread_id="late", start_ordinal=1))
        op = self.core.stage(view, directory=self.root / "exports", adapter=self.adapter)
        self.assertEqual(tail, self.core.package(op)["items"][-2:])
        # No presentation receipt: safe only because this result is still hot.
        with self.assertRaisesRegex(WSCError, "result_presentation_unknown"):
            self.core.capture()

    def test_generation_failure_counted_and_never_retried_implicitly(self):
        snap = self.core.capture()
        def failed(material):
            raise TimeoutError("provider outcome unknown")
        with self.assertRaises(TimeoutError):
            self.core.generate(snap, failed, producer="external_model")
        report = self.core.status()["usage"]
        self.assertEqual("failed", report["attempts"][0]["status"])
        self.assertEqual(1, report["totals"]["input_uncached"]["unknown_attempts"])
        with self.assertRaisesRegex(WSCError, "generation_budget_exhausted"):
            self.core.generate(snap, failed, producer="external_model")

    def test_command_generator_and_usage_receipt(self):
        program = self.root / "generator.py"
        program.write_text('import json,sys\nm=json.load(sys.stdin)\nprint(json.dumps({"selection": '
                           '{"new_understandings":[{"text":"Explicit output", "kind":"diagnosis", '
                           '"sources":[m["events"][0]["id"]]}]}, "usage":{"input_uncached":20,"output":3}}))\n',
                           encoding="utf-8")
        view = self.core.generate(self.core.capture(), JsonCommandGenerator([sys.executable, str(program)]),
                                  producer="offline_command_fixture")
        self.assertTrue(view)
        totals = self.core.status()["usage"]["totals"]
        self.assertEqual(20, totals["input_uncached"]["known_sum"])
        self.assertEqual(1, totals["input_cached"]["unknown_attempts"])

    def test_new_control_during_generation_rejects_but_counts_call(self):
        def generate(material):
            self.core.ingest(self.adapter.import_items([message("user", "Changed goal")], thread_id="control"))
            return Generated(Selection(), Usage(input_uncached=9, output=1))
        with self.assertRaisesRegex(WSCError, "control_changed"):
            self.core.generate(self.core.capture(), generate, producer="test")
        self.assertEqual(9, self.core.status()["usage"]["totals"]["input_uncached"]["known_sum"])
        self.assertEqual(0, self.core.status()["cursor"])

    def test_two_cycles_and_revision_without_new_source(self):
        self.core.install(self.staged(), self.host)
        self.core.install(self.staged(), self.host)
        self.assertEqual(2, self.core.status()["generation"])
        self.assertEqual(5, self.core.status()["source_count"])
        self.assertEqual(5, self.core.status()["cursor"])

    def test_store_binding_and_hash_reject_corruption(self):
        before = (self.root / "wsc.db").read_bytes()
        with self.assertRaisesRegex(WSCError, "store_binding_mismatch"):
            Store(self.root / "wsc.db", session_id="wrong", workspace=str(self.root))
        self.assertEqual(before, (self.root / "wsc.db").read_bytes())
        with self.core.store.transaction() as db:
            db.execute("UPDATE events SET data='{}' WHERE seq=1")
        with self.assertRaisesRegex(WSCError, "source_integrity_mismatch"):
            self.core.capture()

    def test_byte_budget_is_not_a_token_or_semantic_claim(self):
        with self.assertRaisesRegex(WSCError, "view_byte_budget_exhausted"):
            self.view(limits=Limits(max_view_bytes=5))
        with self.core.store.connect() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM understandings").fetchone()[0])
        op = self.staged()
        self.assertEqual("unverified", self.core.package(op)["semantic_status"])
        self.assertFalse(self.core.package(op)["adapter"]["transparent_native_compaction"])

    def test_unknown_native_type_rejects_whole_conversion(self):
        with self.assertRaisesRegex(WSCError, "native_item_type_unsupported"):
            self.adapter.import_items([message("user", "hi"), {"type": "future_type"}], thread_id="new")
        self.assertEqual(5, self.core.status()["source_count"])

    def test_dependency_direction_and_legacy_isolation(self):
        root = Path(__file__).resolve().parents[1] / "src" / "wsc"
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [x.name for x in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                self.assertFalse(any(x.split(".")[0] in {"memory", "engine", "server", "cli", "todo"}
                                     for x in names if not isinstance(node, ast.ImportFrom) or node.level == 0), path)
                if path.parent == root and path.name not in {"cli.py"}:
                    self.assertFalse(any(x.startswith("adapters") for x in names), path)
        import wsc
        self.assertTrue(Path(wsc.__file__).resolve().is_relative_to(root))

    def test_internal_import_graph_is_acyclic(self):
        root = Path(__file__).resolve().parents[1] / "src" / "wsc"
        modules = {p.stem: p for p in root.glob("*.py") if not p.stem.startswith("__")}
        graph = {}
        for name, path in modules.items():
            edges = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    targets = [node.module.split(".")[0]] if node.module else [a.name for a in node.names]
                    edges.update(t for t in targets if t in modules)
            graph[name] = edges
        done = set()
        def visit(name, active):
            self.assertNotIn(name, active, f"circular import: {active} -> {name}")
            if name not in done:
                for target in graph[name]:
                    visit(target, active | {name})
                done.add(name)
        for name in graph:
            visit(name, set())

    def test_control_after_host_commit_preserves_tail_and_allows_next_publication(self):
        """The host commits before the control change; its durable result remains true."""
        op = self.staged()
        tail = message("user", "constraint added after the host committed")

        def commit(pkg):
            receipt = self.host.install(pkg)
            self.core.ingest(self.adapter.import_items(
                [tail], thread_id="after-install"))
            with closing(sqlite3.connect(self.host.path)) as db, db:
                state = self.host.state()
                state["items"].append(tail)
                db.execute("UPDATE state SET data=? WHERE id=1", (encode(state),))
            return receipt

        self.core.install(op, CallbackHost(commit=commit, lookup=self.host.lookup))
        self.assertEqual(1, self.host.state()["effects"])
        self.assertEqual(tail, self.host.state()["items"][-1])
        self.assertEqual("confirmed", self.core.status()["operations"][-1]["state"])
        self.assertEqual(5, self.core.status()["cursor"])
        self.assertEqual(6, self.core.status()["source_count"])
        self.assertTrue(self.staged())


if __name__ == "__main__":
    unittest.main()
