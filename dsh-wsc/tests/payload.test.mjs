import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildCheckpoint, buildSelectiveCheckpoint } from '../lib/checkpoint.js'
import { PAYLOAD_DEFAULTS, collapsePriorEcho, resolvePayloadPolicy } from '../lib/payload.js'

const text = (value) => [{ type: 'text', text: value }]
const user = (value) => ({
  role: 'user',
  content: text(value),
  source: { kind: 'user' },
})

/** Region with one long, non-repeating tool output so a quote binds uniquely. */
const longRegion = () => {
  const body = Array.from({ length: 400 }, (_, index) => `const value${index} = ${index * 7}`).join('\n')
  const lines = body.split('\n')
  return {
    messages: [
      user('Ship the --watch flag.'),
      { role: 'assistant', content: text('Reading the file.') },
      { role: 'tool', content: text(body), toolCallId: 'c1' },
    ],
    body,
    head: (count) => lines.slice(0, count).join('\n'),
  }
}

test('payload: an unset policy is the shipped policy', () => {
  assert.deepEqual(resolvePayloadPolicy(), PAYLOAD_DEFAULTS)
  assert.equal(resolvePayloadPolicy().sourceFraction, 0.35)
  assert.equal(resolvePayloadPolicy().quoteMaxChars, 1200)
  assert.equal(resolvePayloadPolicy().factMaxChars, 320)
  assert.equal(resolvePayloadPolicy().priorEchoDepth, 0)
})

test('payload: flat settings keys resolve and invalid values keep the default', () => {
  const policy = resolvePayloadPolicy({ payloadQuoteMaxChars: 4000, payloadFactMaxChars: 800 })
  assert.equal(policy.quoteMaxChars, 4000)
  assert.equal(policy.factMaxChars, 800)
  assert.equal(policy.selectedItemCap, PAYLOAD_DEFAULTS.selectedItemCap)
  const invalid = resolvePayloadPolicy({ payloadQuoteMaxChars: -1, payloadPriorEchoDepth: -3 })
  assert.equal(invalid.quoteMaxChars, PAYLOAD_DEFAULTS.quoteMaxChars)
  assert.equal(invalid.priorEchoDepth, PAYLOAD_DEFAULTS.priorEchoDepth)
})

test('payload: prior echo beyond the configured depth is dropped', () => {
  const nested = [
    '## Prior checkpoint (historical; re-check current evidence)',
    '- ## Prior checkpoint (historical; re-check current evidence)',
    '  - ## Prior checkpoint (historical; re-check current evidence)',
    '',
    '## Selected excerpts (verbatim; role prefix shows the speaker)',
    '- [s1] [tool:read] the real fact',
  ].join('\n')
  assert.equal(collapsePriorEcho(nested, 0), nested)
  const collapsed = collapsePriorEcho(nested, 1)
  assert.ok(collapsed.includes('the real fact'), 'depth 1 keeps the previous checkpoint body')
  assert.equal(collapsed.includes('- ## Prior checkpoint'), false, 'depth 1 drops the bulleted echo heading')
  assert.equal(collapsed.includes('  - ## Prior checkpoint'), false, 'depth 1 drops the nested echo')
  assert.ok(collapsed.length < nested.length)
})

test('payload: a quote the shipped policy drops is kept by the bypass policy', () => {
  const { messages, head } = longRegion()
  const quote = head(100) // ~1.9k characters: above the shipped 1200 acceptance limit
  assert.ok(quote.length > 1200 && quote.length < 2400)
  const shipped = buildSelectiveCheckpoint({ messages }, { quotes: [quote] })
  const bypass = buildSelectiveCheckpoint(
    { messages },
    { quotes: [quote], payload: { quoteMaxChars: 4000, selectedItemCap: 4000 } },
  )
  assert.equal(shipped, null, 'the 1200-character acceptance limit drops the quote')
  assert.notEqual(bypass, null)
  assert.equal(bypass.selectedCount, 1)
  assert.ok(bypass.payload.sections.selected > 1200, `selected section is ${bypass.payload.sections.selected}`)
})

test('payload: a judgment the shipped policy drops is kept by the bypass policy', () => {
  const { messages, head } = longRegion()
  const quote = head(10)
  const fact = 'x'.repeat(500)
  const shipped = buildSelectiveCheckpoint({ messages }, { quotes: [quote], facts: [{ text: fact, sources: [quote] }] })
  const bypass = buildSelectiveCheckpoint(
    { messages },
    { quotes: [quote], facts: [{ text: fact, sources: [quote] }], payload: { factMaxChars: 800, judgmentItemCap: 800 } },
  )
  assert.equal(shipped.droppedFacts, 1)
  assert.equal(shipped.judgmentCount, 0)
  assert.equal(bypass.droppedFacts, 0)
  assert.equal(bypass.judgmentCount, 1)
})

test('payload: the selective builder reports its own budget and section sizes', () => {
  const { messages, head } = longRegion()
  const built = buildSelectiveCheckpoint({ messages }, { quotes: [head(20)] })
  assert.ok(built.payload.budget > 0)
  assert.ok(built.payload.chars > 0)
  assert.ok(built.payload.chars <= built.payload.budget)
  assert.equal(built.payload.priorDepth, 0)
  assert.ok(built.payload.sections.selected > 0)
})

test('payload: tool-output knobs carry more of a region that is mostly tool output', () => {
  const messages = [user('Ship the --watch flag.')]
  for (let index = 0; index < 12; index += 1) {
    const body = Array.from({ length: 20 }, (_, line) => `const v${index}x${line} = ${line * index}`).join('\n')
    messages.push(
      { role: 'assistant', content: text(`step ${index}`) },
      { role: 'tool', content: text(body), toolCallId: `c${index}` },
    )
  }
  const implicit = buildCheckpoint({ messages })
  const explicit = buildCheckpoint({ messages }, { payload: PAYLOAD_DEFAULTS })
  assert.equal(explicit.text, implicit.text, 'the shipped defaults must not change any output')

  const wide = buildCheckpoint(
    { messages },
    { payload: { sourceFraction: 0.6, outputsWeight: 0.5, outputsItems: 12, outputsItemCap: 1200 } },
  )
  assert.ok(wide.text.length > implicit.text.length * 2, `${wide.text.length} vs ${implicit.text.length}`)
  assert.ok(wide.text.includes('const v0x19'), 'the oldest tool result survives when fewer are dropped')
  assert.equal(implicit.text.includes('const v0x19'), false, 'the shipped policy keeps only the newest six')
})
test('payload: the previous checkpoint carries its body, not its own echo', () => {
  const nestedPrior = [
    '## Prior checkpoint (historical; re-check current evidence)',
    '- ## Prior checkpoint (historical; re-check current evidence)',
    '  - ## Prior checkpoint (historical; re-check current evidence)',
    '',
    '## Selected excerpts (verbatim; role prefix shows the speaker)',
    '- [s1] [tool:read] the only real fact',
  ].join('\n')
  const messages = [
    { role: 'user', content: text(nestedPrior), source: { kind: 'checkpoint' } },
    user('Ship the --watch flag.'),
  ]
  const isCheckpointSource = (source) => source?.kind === 'checkpoint'
  const shipped = buildCheckpoint({ messages }, { isCheckpointSource })
  const collapsed = buildCheckpoint({ messages }, { isCheckpointSource, payload: { priorEchoDepth: 1 } })
  // The echo is dropped before the prior section is allocated, so its budget
  // reaches the previous checkpoint's own content instead of its copy chain.
  assert.ok(shipped.text.includes('the only real fact'), 'the body survives the allocation')
  assert.equal(
    shipped.text.match(/Prior checkpoint/g)?.length,
    1,
    'exactly one prior heading remains, the one this build writes',
  )
  assert.ok(collapsed.text.includes('the only real fact'), 'collapsing the echo leaves room for the body')
  assert.ok(collapsed.text.length <= shipped.text.length)
})
