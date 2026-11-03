import { test } from 'node:test'
import assert from 'node:assert/strict'

import { numberedTranscript, parseSelection, parseSelectionRanges, messageText } from '../lib/selection.js'
import { buildSelectiveCheckpoint } from '../lib/checkpoint.js'

const text = (value) => [{ type: 'text', text: value }]

test('selection: the transcript numbers retained messages and labels their role', () => {
  const messages = [
    { role: 'system', content: text('system rules') },
    { role: 'user', content: text('keep this request') },
    { role: 'assistant', content: [] },
    { role: 'tool', content: text('tool output here'), toolCallId: 'c1' },
  ]
  const { text: projection, addressable } = numberedTranscript(messages)
  assert.equal(addressable, true)
  assert.ok(!projection.includes('system rules'), 'system messages are not part of the region')
  assert.ok(projection.startsWith('[m1 user]\nkeep this request'), 'numbering starts at the first retained message')
  assert.ok(projection.includes('[m3 tool-result]\ntool output here'), 'a text-less message keeps its number')
})

test('selection: an oversized region is not projected, and spans are then refused', () => {
  const huge = 'x'.repeat(500_000)
  const { addressable } = numberedTranscript([{ role: 'user', content: text(huge) }])
  assert.equal(addressable, false)
})

test('selection: a span emitted against the transcript addresses the same message', () => {
  const body = 'the retry policy must not swallow a write error'
  const messages = [
    { role: 'user', content: text('keep this request') },
    { role: 'assistant', content: text(body) },
  ]
  const { text: projection } = numberedTranscript(messages)
  assert.ok(projection.includes('[m2 assistant]'), 'the second retained message is m2')
  const built = buildSelectiveCheckpoint({ messages }, { spans: [{ source: 'm2', start: 4, end: 28 }] })
  assert.equal(built.selectedCount, 1)
  assert.ok(built.text.includes(body.slice(4, 28)))
})

test('selection: a fenced JSON object is parsed and malformed entries are dropped', () => {
  const raw = [
    '```json',
    JSON.stringify({
      keep: ['a long enough quote'],
      spans: [
        { source: 'm2', start: 4, end: 10 },
        { source: 'm2', start: 9, end: 3 },
        { source: 'm2', start: 0.5, end: 3 },
        { start: 0, end: 3 },
      ],
      fragments: [{ source: 'm2', text: 'retry policy' }, { source: 'm2', text: 'ab' }, { text: 'no source' }],
      facts: [{ text: 'a judgment', sources: ['a long enough quote'] }],
    }),
    '```',
  ].join('\n')
  const selection = parseSelection(raw)
  assert.deepEqual(selection.quotes, ['a long enough quote'])
  assert.equal(selection.spans.length, 1)
  assert.equal(selection.fragments.length, 1)
  assert.equal(selection.facts.length, 1)
})

test('selection: unparseable output yields an empty selection', () => {
  for (const raw of ['', 'not json', '{"keep": "not a list"}']) {
    const selection = parseSelection(raw)
    assert.deepEqual(selection, { quotes: [], spans: [], fragments: [], facts: [] })
  }
})

test('selection: message text joins text blocks and ignores other blocks', () => {
  assert.equal(
    messageText({ content: [{ type: 'text', text: 'one' }, { type: 'tool-call', id: 'x' }, { type: 'text', text: 'two' }] }),
    'one\ntwo',
  )
  assert.equal(messageText({ content: 'plain' }), 'plain')
  assert.equal(messageText({ content: [{ type: 'tool-call' }] }), '')
})

test('selection: line mode numbers the body without changing the text', () => {
  const body = 'first line\nsecond line'
  const messages = [{ role: 'assistant', content: text(body) }]
  const { text: projection } = numberedTranscript(messages, { lineNumbers: true })
  assert.ok(projection.includes('1| first line'), 'each line carries its number')
  assert.ok(projection.includes('2| second line'))
})

test('selection: a line range is parsed as an address, not as content', () => {
  const raw = [
    '```json',
    JSON.stringify({
      keep: [
        { source: 'm2', lines: [3, 9] },
        { source: 'm2', lines: [5, 500] },
        { source: 'm2', lines: [0, 4] },
        { source: 'm2', lines: [9, 3] },
        { lines: [1, 2] },
      ],
      facts: [{ text: 'a judgment', sources: ['m2'] }],
    }),
    '```',
  ].join('\n')
  const selection = parseSelectionRanges(raw)
  assert.deepEqual(selection.ranges, [
    { source: 'm2', from: 3, to: 9 },
    { source: 'm2', from: 5, to: 64 },
  ])
  assert.equal(selection.facts.length, 1)
})

test('selection: a line range resolves to exactly those lines', () => {
  const body = 'alpha beta\ngamma delta\nepsilon zeta\neta theta'
  const messages = [{ role: 'assistant', content: text(body) }]
  const built = buildSelectiveCheckpoint(
    { messages },
    { ranges: [{ source: 'm1', from: 2, to: 3 }] },
  )
  assert.equal(built.selectedCount, 1)
  assert.ok(built.text.includes('gamma delta'), 'the addressed lines are copied verbatim')
  assert.ok(built.text.includes('epsilon zeta'))
  assert.ok(!built.text.includes('alpha beta'), 'lines outside the range are not copied')
  assert.ok(!built.text.includes('2| '), 'the transcript numbering never reaches the checkpoint')
})

test('selection: a line range past the end of the message is dropped', () => {
  const messages = [{ role: 'assistant', content: text('only one line') }]
  const built = buildSelectiveCheckpoint({ messages }, { ranges: [{ source: 'm1', from: 9, to: 12 }] })
  assert.equal(built, null)
})
