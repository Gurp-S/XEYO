import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildWorkingSet, createWorkingSet } from '../lib/workingset-v2.js'

const call = (id, name, args) => ({ type: 'tool-call', id, name, arguments: JSON.stringify(args) })
const asst = (text, ...calls) => ({ role: 'assistant', content: [{ type: 'text', text }, ...calls] })
const result = (callId, body) => ({
  role: 'user',
  toolCallId: callId,
  content: [{ type: 'text', text: `<path>x</path>\n<content>\n${body}\n</content>` }],
})

const readThenEdit = (body = 'line one\nline two') => [
  asst('Checking the planner resolver.', call('c1', 'read', { path: 'src/planner.js' })),
  result('c1', body),
  asst('Rewriting the resolver.', call('c2', 'edit', { path: 'src/planner.js', old_string: 'line one', new_string: 'line 1' })),
]

test('an edited file keeps its body and carries the delta', () => {
  const text = buildWorkingSet(readThenEdit()).join('\n')
  assert.match(text, /src\/planner\.js — read #0/)
  assert.match(text, /edited #2 \(\+1\/−1\): "line 1"/)
  assert.match(text, /line two/)
})

test('a read with no later touch quotes its own role', () => {
  const text = buildWorkingSet(readThenEdit().slice(0, 2)).join('\n')
  assert.match(text, /role: "Checking the planner resolver\."/)
})

test('the role line follows the latest touch, not the read', () => {
  const text = buildWorkingSet([
    ...readThenEdit(),
    asst('Caching the resolver result.', call('c3', 'edit', { path: 'src/planner.js', old_string: 'line 1', new_string: 'line 1 cached' })),
  ]).join('\n')
  assert.match(text, /role at #\d+: "Caching the resolver result\."/)
  assert.doesNotMatch(text, /role: "Checking the planner resolver\./)
})

test('a section re-parsed from a checkpoint keeps body, role and delta', () => {
  const first = buildWorkingSet(readThenEdit()).join('\n')
  const again = buildWorkingSet([], { seed: `## Working set\n\n${first}\n` }).join('\n')
  assert.match(again, /line two/)
  assert.match(again, /role at #2: "Rewriting the resolver\."/)
  assert.match(again, /edited #2 \(\+1\/−1\)/)
})

test('a re-read clears edits it already contains', () => {
  const tracker = createWorkingSet()
  tracker.apply(readThenEdit())
  tracker.apply([
    asst('Re-reading.', call('c3', 'read', { path: 'src/planner.js' })),
    result('c3', 'line 1\nline two'),
  ])
  assert.doesNotMatch(tracker.items().join('\n'), /edited #/)
})

test('the section never exceeds its ceiling and drops whole files', () => {
  const messages = []
  for (let i = 0; i < 6; i += 1) {
    messages.push(asst(`Reading file ${i}.`, call(`r${i}`, 'read', { path: `f${i}.js` })))
    messages.push(result(`r${i}`, 'x'.repeat(700)))
  }
  const items = buildWorkingSet(messages, { sectionCap: 1600 })
  assert.ok(items.join('\n').length <= 1600)
  assert.ok(items.length >= 1)
  assert.doesNotMatch(items.join('\n'), /…/)
})
