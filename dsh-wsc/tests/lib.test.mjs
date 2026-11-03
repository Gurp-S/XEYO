import { test } from 'node:test'
import assert from 'node:assert/strict'

import { decide, adjust, usedPercent } from '../lib/timing.js'
import { buildCheckpoint, buildSelectiveCheckpoint } from '../lib/checkpoint.js'
import {
  stripNoiseLines,
  collapseStack,
  truncateHeadTail,
  outlineJson,
  diffDigest,
  applyDenoise,
  ALL_DENOISE_RULES,
} from '../lib/denoise.js'

const text = (value) => [{ type: 'text', text: value }]

test('timing: 80% notifies, 85% forces, below 80% keeps', () => {
  assert.deepEqual(decide(7900, 10000), { tokens: 7900, capacity: 10000, action: 'keep', notify: false })
  assert.deepEqual(decide(8000, 10000), { tokens: 8000, capacity: 10000, action: 'keep', notify: true })
  assert.deepEqual(decide(8500, 10000), { tokens: 8500, capacity: 10000, action: 'capacity', notify: true })
})

test('timing: a notified session is not notified again', () => {
  assert.equal(decide(8000, 10000, { notified: true }).notify, false)
})

test('timing: no capacity means no pressure', () => {
  assert.deepEqual(decide(50000, 0), { tokens: 50000, capacity: 0, action: 'keep', notify: false })
})

test('timing: integer cross multiplication does not round a threshold down', () => {
  // 1/3 is 33.33%: it must not reach a 34% boundary, but must reach 33%.
  assert.equal(decide(1, 3, { forcePercent: 34 }).action, 'keep')
  assert.equal(decide(1, 3, { forcePercent: 33 }).action, 'capacity')
})

test('timing: one session walks keep, notify once, force, then the hard bound', () => {
  const capacity = 10000
  const steps = [
    { tokens: 7500, expect: { action: 'keep', notify: false } },
    { tokens: 8000, expect: { action: 'keep', notify: true } },
    { tokens: 8200, notified: true, expect: { action: 'keep', notify: false } },
    { tokens: 8500, notified: true, expect: { action: 'capacity', notify: false } },
    { tokens: 9000, notified: true, expect: { action: 'capacity', notify: false } },
    { tokens: 10000, notified: true, expect: { action: 'capacity', notify: false } },
  ]
  let notified = false
  for (const step of steps) {
    const decision = decide(step.tokens, capacity, { notified: step.notified ?? notified })
    assert.equal(decision.action, step.expect.action, `at ${step.tokens}`)
    assert.equal(decision.notify, step.expect.notify, `notify at ${step.tokens}`)
    if (decision.notify) notified = true
    const adjusted = adjust(decision)
    assert.equal(adjusted.action, step.expect.action, `adjusted at ${step.tokens}`)
  }
})

test('timing: an early capacity action degrades to a soft keep', () => {
  const early = { tokens: 8000, capacity: 10000, action: 'capacity', notify: true }
  assert.equal(adjust(early).action, 'keep')
  const hard = { tokens: 9000, capacity: 10000, action: 'capacity', notify: true }
  assert.equal(adjust(hard).action, 'capacity')
  assert.equal(adjust(hard), hard)
})

test('timing: usedPercent truncates to one decimal', () => {
  assert.equal(usedPercent(1, 3), 33.3)
  assert.equal(usedPercent(5, 0), 0)
})

test('checkpoint: empty region yields an empty checkpoint', () => {
  assert.deepEqual(buildCheckpoint({ messages: [] }), { text: '', sourceBytes: 0, budget: 0 })
})

test('checkpoint: system messages are not source, and the budget is 35% of source bytes', () => {
  const messages = [
    { role: 'system', content: text('SYSTEM-PREAMBLE-MUST-NOT-APPEAR') },
    { role: 'user', content: text('the parser must reject an empty path') },
    { role: 'assistant', content: text('I will read the file first') },
  ]
  const built = buildCheckpoint({ messages })
  const source = messages.filter((m) => m.role !== 'system')
  const sourceBytes = source.reduce((total, m) => total + Buffer.byteLength(JSON.stringify(m.content), 'utf8'), 0)
  assert.equal(built.sourceBytes, sourceBytes)
  assert.equal(built.budget, Math.min(24000, Math.max(600, Math.floor(sourceBytes * 0.35))))
  assert.ok(!built.text.includes('SYSTEM-PREAMBLE-MUST-NOT-APPEAR'))
  assert.ok(Buffer.byteLength(built.text, 'utf8') <= built.budget, 'checkpoint must respect its byte budget')
})

test('checkpoint: a CJK region is budgeted in UTF-8 bytes, not characters', () => {
  const messages = [{ role: 'user', content: text('用户要求把整个校验器改成按字节计量的预算'.repeat(40)) }]
  const built = buildCheckpoint({ messages })
  const chars = JSON.stringify(messages[0].content).length
  assert.ok(built.sourceBytes > chars, 'CJK source must measure more bytes than characters')
  assert.equal(built.budget, Math.min(24000, Math.max(600, Math.floor(built.sourceBytes * 0.35))))
  assert.ok(Buffer.byteLength(built.text, 'utf8') <= built.budget)
})

test('checkpoint: maxChars caps the budget', () => {
  const built = buildCheckpoint({ messages: [{ role: 'user', content: text('x'.repeat(5000)) }] }, { maxChars: 700 })
  assert.equal(built.budget, 700)
  assert.ok(Buffer.byteLength(built.text, 'utf8') <= 700)
})

test('checkpoint: the control section keeps a long task prompt whole when the cap allows', () => {
  // Regression for the WSC trial failure: a 1345-character request whose
  // acceptance criterion sat at the end was cut at 800 bytes, so the checkpoint
  // said "rebuild" and lost "on --watch".
  const task = `${'Investigate the repository and report the cause. '.repeat(32)}Implement --watch rebuilds.`
  assert.ok(task.length > 1345)
  const messages = [
    { role: 'user', source: { kind: 'user' }, content: text(task) },
    { role: 'assistant', content: text('log line: build finished without errors '.repeat(600)) },
  ]
  const built = buildCheckpoint({ messages }, { controlItemCap: 4000 })
  assert.ok(built.text.includes(task), 'the whole request must appear verbatim')
  assert.equal(built.control.cap, 4000)

  const shipped = buildCheckpoint({ messages })
  assert.ok(!shipped.text.includes('--watch'), 'the 800 default still truncates, so the fix is opt-in')
})

test('checkpoint: controlItemCap 0 removes the per-item cap', () => {
  const task = `${'padding sentence. '.repeat(200)}Acceptance: --watch rebuilds.`
  const messages = [
    { role: 'user', source: { kind: 'user' }, content: text(task) },
    { role: 'assistant', content: text('log line: build finished without errors '.repeat(600)) },
  ]
  const built = buildCheckpoint({ messages }, { controlItemCap: 0 })
  assert.equal(built.control.cap, null)
  assert.ok(built.text.includes(task))
})

test('checkpoint: a region without the prompt carries the control section forward', () => {
  // The prompt is in the region only until the first compaction; after that the
  // previous checkpoint's control section is the only copy, and it must survive
  // however little of the prior text the prior section's cap allows.
  const prior = [
    '## User requests (verbatim, control)',
    '- Ship the --watch flag.',
    '',
    '## Working set (file state the model last saw)',
    '- src/a.js — read #3',
  ].join('\n')
  const messages = [
    { role: 'user', content: text(prior), source: { kind: 'checkpoint' } },
    { role: 'assistant', content: text('working on it') },
  ]
  const isCheckpointSource = (source) => source?.kind === 'checkpoint'
  const built = buildCheckpoint({ messages }, { isCheckpointSource })
  assert.ok(built.text.includes('## User requests'), 'the control section is present')
  assert.ok(built.text.includes('Ship the --watch flag.'), 'the request is carried forward')

  const selective = buildSelectiveCheckpoint(
    { messages },
    { quotes: ['working on it'], facts: [], isCheckpointSource },
  )
  assert.ok(selective.text.includes('Ship the --watch flag.'), 'the selective build carries it too')
})

test('checkpoint: the control section renders before the prior echo', () => {
  // Regression for the echo column: the prior section used to be rendered
  // first, so a checkpoint cut at its budget kept a copy of the previous
  // checkpoint and dropped the request it was meant to carry.
  const prior = '## Prior checkpoint (historical; re-check current evidence)\n- an old fact\n'
  const messages = [
    { role: 'user', content: text(prior.repeat(40)), source: { kind: 'checkpoint' } },
    { role: 'user', source: { kind: 'user' }, content: text('Ship the --watch flag.') },
  ]
  const built = buildCheckpoint(
    { messages },
    { isCheckpointSource: (source) => source?.kind === 'checkpoint', maxChars: 900 },
  )
  assert.ok(
    built.text.indexOf('## User requests') < built.text.indexOf('## Prior checkpoint'),
    'the control section comes first',
  )
  assert.ok(built.text.includes('--watch'), 'a tight budget still carries the request')
})

test('selective: the control section keeps a long task prompt whole when the cap allows', () => {
  const task = `${'Investigate the repository and report the cause. '.repeat(32)}Implement --watch rebuilds.`
  const decision = 'decided: keep the retry policy as it is'
  const messages = [
    { role: 'user', source: { kind: 'user' }, content: text(task) },
    { role: 'assistant', content: text(decision) },
    { role: 'assistant', content: text('log line: build finished without errors '.repeat(600)) },
  ]
  const built = buildSelectiveCheckpoint(
    { messages },
    { quotes: [decision], facts: [], controlItemCap: 4000 },
  )
  assert.ok(built.text.includes(task))
  assert.equal(built.control.cap, 4000)
})

test('selective: a span selects exact bytes from a named message', () => {
  const body = 'the retry policy must not swallow a write error after the first commit'
  const messages = [
    { role: 'user', content: text('keep this request') },
    { role: 'assistant', content: text(body) },
  ]
  const built = buildSelectiveCheckpoint({ messages }, { spans: [{ source: 'm2', start: 4, end: 28 }] })
  assert.equal(built.selectedCount, 1)
  assert.equal(built.droppedExcerpts, 0)
  assert.ok(built.text.includes(body.slice(4, 28)))
})

test('selective: an exact fragment selects only when it is unique', () => {
  const messages = [
    { role: 'user', content: text('keep this request') },
    { role: 'assistant', content: text('the retry policy must not swallow a write error') },
  ]
  const built = buildSelectiveCheckpoint({ messages }, { fragments: [{ source: 2, text: 'retry policy' }] })
  assert.equal(built.selectedCount, 1)
  assert.ok(built.text.includes('retry policy'))
})

test('selective: a kept judgment is exposed with the refs it cited', () => {
  const quote = 'the retry policy must not swallow a write error'
  const messages = [{ role: 'assistant', content: text(quote) }]
  const built = buildSelectiveCheckpoint(
    { messages },
    {
      quotes: [quote],
      facts: [
        { text: 'retry errors surface after the first commit', sources: [quote] },
        { text: 'an unsourced claim', sources: ['not a kept quote'] },
      ],
    },
  )
  assert.equal(built.judgmentCount, 1)
  assert.equal(built.droppedFacts, 1)
  assert.deepEqual(built.keptFacts, [
    { text: 'retry errors surface after the first commit', sources: ['s1'] },
  ])
  assert.ok(built.text.includes('[s1]'))
})

test('selective: an unusable address is dropped, and nothing else selected yields null', () => {
  const messages = [
    { role: 'user', content: text('keep this request') },
    { role: 'assistant', content: text('the retry policy must not swallow a write error') },
  ]
  assert.equal(buildSelectiveCheckpoint({ messages }, { spans: [{ source: 'm9', start: 0, end: 5 }] }), null)
  const built = buildSelectiveCheckpoint(
    { messages },
    { spans: [{ source: 'm9', start: 0, end: 5 }], quotes: ['swallow a write error'] },
  )
  assert.equal(built.droppedExcerpts, 1)
  assert.equal(built.selectedCount, 1)
})

test('denoise: ANSI, progress rewrites and pytest dots are stripped', () => {
  const raw = [
    '\x1b[31merror: it failed\x1b[0m',
    'Downloading 10%\rDownloading 90%',
    '........s.....',
    'the parser must reject an empty path',
    '',
    '',
    '',
  ].join('\n')
  const stripped = stripNoiseLines(raw)
  assert.ok(!stripped.includes('\x1b['), 'ANSI escapes must be removed')
  assert.ok(!stripped.includes('Downloading 10%'), 'only the final carriage-return segment survives')
  assert.ok(stripped.includes('Downloading 90%'))
  assert.ok(!stripped.split('\n').some((line) => /^[.sFE]{8,}$/.test(line.trim())), 'pytest dots are noise')
  assert.ok(stripped.includes('the parser must reject an empty path'))
  assert.ok(!stripped.includes('\n\n\n'), 'blank runs collapse')
})

test('denoise: identical consecutive lines collapse to one line plus a count', () => {
  const collapsed = collapseStack('Error: boom\n  at fn (file.js:1:1)\n  at fn (file.js:1:1)\n  at fn (file.js:1:1)')
  assert.equal(collapsed.split('\n').length, 2)
  assert.ok(collapsed.endsWith('×3'))
})

test('denoise: truncateHeadTail keeps both ends and respects the cap', () => {
  const raw = 'H'.repeat(2000) + 'M'.repeat(2000) + 'T'.repeat(2000)
  const out = truncateHeadTail(raw, 800, 300)
  assert.ok(out.length <= 800 + 300 + 200)
  assert.ok(out.startsWith('H'))
  assert.ok(out.endsWith('T'))
})

test('denoise: JSON is outlined rather than cut mid-token', () => {
  const raw = JSON.stringify({ alpha: 1, beta: [1, 2, 3], gamma: { delta: 'value' } }, null, 2)
  const out = outlineJson(raw, 40)
  assert.ok(out.length > 0)
  assert.ok(out.split('\n').length <= 40)
})

test('denoise: diffDigest is deterministic and equal for equal input', () => {
  const a = diffDigest('line one\nline two')
  assert.equal(a, diffDigest('line one\nline two'))
  assert.notEqual(a, diffDigest('line one\nline three'))
})

test('denoise: applyDenoise returns a message list of the same length', () => {
  const messages = [{ role: 'tool', content: text('x'.repeat(4000)) }]
  const applied = applyDenoise(messages, ALL_DENOISE_RULES)
  assert.equal(applied.messages.length, messages.length)
})

test('selective: a tight budget keeps the working set instead of truncating it away', () => {
  const task = 'Fix the cache invalidation bug in lib/cache.js. '.repeat(12)
  const decision = 'decided: the cache key stays the resolved file path'
  const body = `export function cache(key) { return key } // ${'padding '.repeat(600)}`
  const messages = [
    { role: 'user', source: { kind: 'user' }, content: text(task) },
    {
      role: 'assistant',
      content: [{ type: 'tool-call', id: 'c1', name: 'read', arguments: JSON.stringify({ path: 'lib/cache.js' }) }],
    },
    {
      role: 'user',
      toolCallId: 'c1',
      source: { kind: 'tool', callId: 'c1' },
      content: text(`<path>lib/cache.js</path>\n<type>file</type>\n<content>\n${body}\n</content>`),
    },
    { role: 'assistant', content: text(decision) },
    { role: 'assistant', content: text('log line '.repeat(400)) },
  ]
  const built = buildSelectiveCheckpoint(
    { messages },
    { maxChars: 1400, quotes: [decision], workingset: { maxFiles: 4, capChars: 300 } },
  )
  assert.ok(built.text.includes('## Working set'))
  assert.ok(built.text.includes('lib/cache.js'))
  assert.equal(built.payload.truncated, false)
})