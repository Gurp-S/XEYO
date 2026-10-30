import sqlite3
import unittest

from wsc import query_ledger
from wsc.source_access import SourceAccessLimits


class QueryLedgerChecks(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)

    def test_spend_accumulates_across_connections(self):
        query_ledger.spend(self.db, "s:10", calls=2, rows=3, text_bytes=100)
        again = sqlite3.connect(":memory:")
        self.addCleanup(again.close)
        self.assertEqual(dict(calls=2, rows=3, text_bytes=100),
                         query_ledger.totals(self.db, "s:10"))

    def test_totals_of_an_unknown_key_are_zero(self):
        self.assertEqual(dict(calls=0, rows=0, text_bytes=0),
                         query_ledger.totals(self.db, "missing"))

    def test_enforce_rejects_a_key_over_its_ceiling(self):
        limits = SourceAccessLimits(max_calls=2, max_rows_total=10, max_text_bytes_total=1000)
        query_ledger.spend(self.db, "s:1", calls=2, rows=1, text_bytes=10)
        query_ledger.enforce(self.db, "s:1", limits)
        query_ledger.spend(self.db, "s:1", calls=1, rows=0, text_bytes=0)
        with self.assertRaises(Exception):
            query_ledger.enforce(self.db, "s:1", limits)


if __name__ == "__main__":
    unittest.main()
