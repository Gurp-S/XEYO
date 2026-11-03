import assert from 'node:assert/strict'
import { test } from 'node:test'

import { buildSelectiveCheckpoint } from '../lib/checkpoint.js'

const text = (value) => [{ type: 'text', text: value }]

const call = (id, name) => ({ role: 'assistant', content: [{ type: 'tool-call', id, name, arguments: '{}' }] })
// The live region's shape: a user message whose content is a tool-result block
// wrapping the result's text, with the call id on the block and on the source.
// A fixture that used plain `text` blocks would pass while the real region
// yielded nothing, so this shape is the point of the test.
const result = (id, body) => ({
  role: 'user',
  source: { kind: 'tool', callId: id },
  content: [{ type: 'tool-result', toolCallId: id, content: text(body) }],
})

const region = (outputs) => [
  { role: 'user', content: text('fix the build') },
  call('c1', 'pwsh'),
  result('c1', outputs[0]),
  call('c2', 'pwsh'),
  result('c2', outputs[1]),
]

test('outputs: recent tool output fills the checkpoint under its heading', () => {
  const built = buildSelectiveCheckpoint(
    { messages: region(['first output: 3 tests failed', 'second output: 3 tests passed']) },
    { quotes: ['fix the build'], facts: [], outputs: { items: 10, cap: 900 } },
  )
  assert.match(built.text, /## Recent tool results/)
  assert.match(built.text, /\[o1\] \[tool:pwsh\] first output/)
  assert.match(built.text, /\[o2\] \[tool:pwsh\] second output/)
  // Filled last, so the budget it reports is what the section actually claimed.
  assert.ok(built.payload.sections.outputs > 0)
})

test('outputs: the section is absent unless asked for', () => {
  const built = buildSelectiveCheckpoint(
    { messages: region(['first output: 3 tests failed', 'second output: 3 tests passed']) },
    { quotes: ['fix the build'], facts: [] },
  )
  assert.doesNotMatch(built.text, /## Recent tool results/)
  assert.equal(built.payload.sections.outputs, undefined)
})

test('outputs: one long result is capped and older results drop first', () => {
  const long = `head ${'x'.repeat(5000)}`
  const built = buildSelectiveCheckpoint(
    { messages: region([long, 'newest output']) },
    { quotes: ['fix the build'], facts: [], outputs: { items: 1, cap: 200 } },
  )
  assert.match(built.text, /\[o1\] \[tool:pwsh\] newest output/)
  assert.doesNotMatch(built.text, /x{300}/)
})
