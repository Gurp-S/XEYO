import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from wsc.contracts import WSCError
from wsc.integrity import advance, install, verify
from wsc.store import Store


class IntegrityChainChecks(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = Store(self.root / "core.db", session_id="session", workspace=str(self.root))

    def seed(self, db, count, offset=0):
        rows = []
        for index in range(count):
            data = '{"i":%d}' % (offset + index)
            rows.append((f"e{offset + index}", data, sha256(data.encode("utf-8")).hexdigest(), "message"))
        db.executemany("INSERT INTO events(id,data,digest,kind,call_id) VALUES (?,?,?,?,NULL)", rows)

    def test_advance_links_every_row_and_verify_is_incremental(self):
        with self.store.transaction() as db:
            self.seed(db, 5)
            self.assertEqual(5, advance(db)["scanned"])
        with self.store.transaction() as db:
            self.assertEqual(0, advance(db)["scanned"])
            result = verify(db)
            self.assertEqual(5, result["scanned"])
            self.assertEqual(5, result["through"])
            self.assertEqual(0, verify(db)["scanned"])

    def test_rewritten_text_is_detected(self):
        with self.store.transaction() as db:
            self.seed(db, 3)
            advance(db)
        with self.store.transaction() as db:
            db.execute("UPDATE events SET data='{\"i\":99}' WHERE seq=2")
            with self.assertRaises(WSCError) as caught:
                verify(db, full=True)
        self.assertEqual("source_integrity_mismatch", str(caught.exception))

    def test_missing_chain_row_is_detected(self):
        with self.store.transaction() as db:
            self.seed(db, 3)
            advance(db)
        with self.store.transaction() as db:
            db.execute("DELETE FROM wsc_event_chain_v1 WHERE seq=2")
            with self.assertRaises(WSCError) as caught:
                verify(db, full=True)
        self.assertEqual("integrity_chain_broken", str(caught.exception))

    def test_append_cost_does_not_grow_with_history(self):
        measured = []
        total = 0
        with self.store.transaction() as db:
            install(db)
        for size in (1000, 5000, 10000, 50000):
            with self.store.transaction() as db:
                self.seed(db, size, offset=total)
                self.assertEqual(size, advance(db)["scanned"])
                verify(db)
                total += size
            with self.store.transaction() as db:
                self.seed(db, 1, offset=total)
                total += 1
                appended = advance(db)["scanned"]
                verified = verify(db)["scanned"]
            self.assertEqual(1, appended)
            self.assertEqual(1, verified)
            measured.append((total, appended, verified))
        self.assertEqual([(1001, 1, 1), (6002, 1, 1), (16003, 1, 1), (66004, 1, 1)], measured)


if __name__ == "__main__":
    unittest.main()
