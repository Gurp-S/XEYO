import { test } from 'node:test'
import assert from 'node:assert/strict'

import { eventAt } from '../lib/session.js'

// The engine must run on both Session shapes the harness has shipped: an
// `eventAt(seq)` accessor and the cached `eventsSnapshot` / `events` arrays.
// A regression here is silent — the pre-step catch turns the failure into a
// warn and compaction simply never happens.

test('session: an eventAt accessor is used when the build provides one', () => {
  const calls = []
  const session = {
    eventAt(seq) {
      calls.push(seq)
      return { seq, type: 'message' }
    },
    eventsSnapshot: [],
  }
  assert.deepEqual(eventAt(session, 7), { seq: 7, type: 'message' })
  assert.deepEqual(calls, [7])
})

test('session: the event is found in a snapshot array when there is no accessor', () => {
  const session = { eventsSnapshot: [{ seq: 1 }, { seq: 2, type: 'assistant/message' }, { seq: 3 }] }
  assert.deepEqual(eventAt(session, 2), { seq: 2, type: 'assistant/message' })
})

test('session: an unknown seq is undefined rather than a throw', () => {
  assert.equal(eventAt({ eventsSnapshot: [{ seq: 1 }] }, 9), undefined)
  assert.equal(eventAt({}, 1), undefined)
  assert.equal(eventAt(undefined, 1), undefined)
})

test('session: a non-array snapshot is treated as absent', () => {
  assert.equal(eventAt({ eventsSnapshot: undefined }, 1), undefined)
  assert.equal(eventAt({ eventsSnapshot: null }, 1), undefined)
})
