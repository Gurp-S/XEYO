import json
import unittest
from unittest import mock

from wsc.contracts import digest
from wsc.context_runtime import ContextRuntime
from wsc.tool_results import ResultPolicy
from tests.test_context_runtime import ContextRuntimeChecks


class QueryReuseChecks(ContextRuntimeChecks):
    def runtime_with(self, query_policy):
        return ContextRuntime(self.core, self.store, policy=ResultPolicy(enabled=True),
                              query_policy=query_policy)

    def read_source(self, context, snapshot, reference):
        return context.query_tool(snapshot).call(
            dict(operation="read", reference=reference, units="unicode_codepoints",
                 offset=0, limit=8))

    def test_reused_reader_hashes_only_the_read_row(self):
        context = self.runtime_with("reader_reuse_v1")
        _, visible, _ = self.result()
        reference = 'source:s' + str(self.ctx.references.get(result_id=visible['result_id'])['source_seq'])
        snapshot = context.capture()
        self.assertEqual("success", self.read_source(context, snapshot, reference).status)
        with mock.patch("wsc.source_access.digest", wraps=digest) as counted:
            value = self.read_source(context, snapshot, reference)
        self.assertEqual("success", value.status, value.text)
        self.assertEqual(1, counted.call_count)

    def test_default_policy_rehashes_the_whole_snapshot_each_query(self):
        context = self.runtime_with("per_query_v1")
        _, visible, _ = self.result()
        reference = 'source:s' + str(self.ctx.references.get(result_id=visible['result_id'])['source_seq'])
        snapshot = context.capture()
        self.assertEqual("success", self.read_source(context, snapshot, reference).status)
        with mock.patch("wsc.source_access.digest", wraps=digest) as counted:
            value = self.read_source(context, snapshot, reference)
        self.assertEqual("success", value.status, value.text)
        self.assertGreater(counted.call_count, 1)

    def test_result_read_validates_the_binding_once_per_query(self):
        context = self.runtime_with("reader_reuse_v1")
        _, visible, _ = self.result()
        with mock.patch.object(context.references, "validate",
                               wraps=context.references.validate) as counted:
            value = context.query_tool(context.capture()).call(
                dict(operation="read", reference="result:" + visible["result_id"],
                     units="utf8_bytes", offset=0, limit=16))
        self.assertEqual("success", value.status, value.text)
        self.assertEqual(1, counted.call_count)

    def test_reused_reader_keeps_per_query_budgets(self):
        context = self.runtime_with("reader_reuse_v1")
        _, visible, _ = self.result()
        snapshot = context.capture()
        for _ in range(2):
            value = self.read_source(context, snapshot, ('source:s' + str(self.ctx.references.get(result_id=visible['result_id'])['source_seq'])))
            self.assertEqual("success", value.status, value.text)
            self.assertEqual(1, json.loads(value.text)["metrics"]["calls"])


if __name__ == "__main__":
    unittest.main()
