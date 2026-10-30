"""Before/after recovery contract checks, without model inference."""
from unittest import TestCase, main
import json
import test_context_runtime as fixtures


class CoordinatePolicyChecks(TestCase):
    setUp = fixtures.ContextRuntimeChecks.setUp
    observe = fixtures.ContextRuntimeChecks.observe
    result = fixtures.ContextRuntimeChecks.result

    def tools(self):
        event, view, _ = self.result()
        snapshot = self.ctx.capture()
        return event, view, self.ctx.query_tool(snapshot), self.ctx.query_tool(
            snapshot, infer_json_pointer_units=True)

    def test_before_after_and_explicit_result_equal_without_mutating_request(self):
        _, view, before, after = self.tools()
        args = dict(operation='json_pointer', reference='result:'+view['result_id'], pointer='/value')
        self.assertEqual('context_range_units_mismatch', json.loads(before.call(args).text)['code'])
        explicit = before.query({**args, 'units': 'json_pointer'})
        self.assertEqual(explicit, after.query(args))
        self.assertNotIn('units', args)
        self.assertEqual('json_pointer', explicit['range_units'])

    def test_explicit_wrong_units_and_ranges_still_rejected(self):
        _, view, _, after = self.tools()
        ref = 'result:'+view['result_id']
        for args in [dict(operation='json_pointer', reference=ref, pointer='/value', units='utf8_bytes'),
                     dict(operation='json_pointer', reference=ref, pointer='/value', units=None),
                     dict(operation='read', reference=ref, offset=0),
                     dict(operation='read_lines', reference=ref),
                     dict(operation='find', reference=ref, literal='value'),
                     dict(operation='read', reference='source:s3', offset=0)]:
            with self.subTest(args=args):
                with self.assertRaisesRegex(ValueError, 'units_mismatch'):
                    after.query(args)

    def test_authorization_snapshot_and_budget_still_enforced(self):
        event, view, _, after = self.tools()
        args = dict(operation='json_pointer', reference='result:'+view['result_id'], pointer='/value')
        self.result_denied.add(view['result_id'])
        self.assertEqual('error', after.call(args).status)
        self.result_denied.clear(); self.denied.add(event.id)
        self.assertEqual('error', after.call(args).status)
        self.denied.clear()
        _, future, _ = self.result(2)
        with self.assertRaisesRegex(ValueError, 'outside_snapshot'):
            after.query({**args, 'reference':'result:'+future['result_id']})
        self.ctx.max_queries = self.ctx.query_calls
        with self.assertRaisesRegex(ValueError, 'call_limit'):
            after.query(args)

    def test_policy_is_explicit_and_definition_is_isolated(self):
        _, _, before, after = self.tools()
        self.assertNotEqual(before.definition()['description'], after.definition()['description'])
        self.assertEqual(before.definition()['inputSchema'], after.definition()['inputSchema'])
        with self.assertRaisesRegex(ValueError, 'policy_invalid'):
            self.ctx.query_tool(self.ctx.capture(), infer_json_pointer_units=1)


if __name__ == '__main__':
    main()
