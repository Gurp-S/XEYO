/**
 * End-to-end: one selective compaction from checkpoint bytes to a durable,
 * verified install — package digest, operation lifecycle, evidence index,
 * understanding record, exported-object lease and re-check.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { buildCheckpoint, buildSelectiveCheckpoint } from '../lib/checkpoint.js'
import { canonicalJson, digest, loadEvidence, read, recordEvidence, sessionStore } from '../lib/evidence.js'
import { confirm, loadOperations, recordOperation } from '../lib/publication.js'
import { ResourceIO, checkEvidence } from '../lib/resources.js'
import { UnderstandingStore } from '../lib/understanding.js'
import { byteLength } from '../lib/bytes.js'
import { sha256Hex } from '../lib/excerpts.js'

const text = (value) => [{ type: 'text', text: value }]

test('integration: a selective checkpoint becomes a confirmed, evidenced install', () => {
  const home = mkdtempSync(join(tmpdir(), 'wsc-e2e-'))
  const quote = 'the retry policy must not swallow a write error'
  const message = { role: 'assistant', content: text(quote) }
  const messages = [{ role: 'user', content: text('keep this request') }, message]

  // 1. The model selects a quote and states a judgment that cites it.
  const built = buildSelectiveCheckpoint(
    { messages },
    {
      quotes: [quote],
      facts: [{ text: 'retry errors surface after the first commit', sources: [quote] }],
    },
  )
  assert.equal(built.selectedCount, 1)
  assert.equal(built.keptFacts.length, 1)

  // 2. The package this engine is about to publish is recorded before publish.
  const blocks = [{ type: 'text', text: built.text }]
  const packageDigest = sha256Hex(canonicalJson(blocks))
  recordOperation(home, 'sess', {
    id: packageDigest,
    state: 'ready',
    at: 't0',
    package: {
      sessionId: 'sess',
      provider: 'p',
      model: 'm',
      throughSeq: 5,
      packageDigest,
      judgments: built.keptFacts,
    },
  })
  const operation = loadOperations(home, 'sess').get(packageDigest)
  assert.equal(operation.state, 'ready')

  // 3. The install is confirmed only against that digest.
  const done = confirm(operation, {
    operationId: operation.id,
    packageDigest,
    sessionId: 'sess',
    provider: 'p',
    model: 'm',
    installedThrough: 5,
    receiver: 'session-log',
    evidenceAccessible: true,
  })
  assert.equal(done.state, 'confirmed')
  recordOperation(home, 'sess', { id: done.id, state: done.state, at: 't1', receipt: done.receipt })
  assert.equal(loadOperations(home, 'sess').get(packageDigest).state, 'confirmed')

  // 4. The shadowed observation is now evidence, readable by digest.
  assert.equal(
    recordEvidence(home, 'sess', [
      { seq: 3, digest: digest(message), bytes: byteLength(canonicalJson(message)) },
    ]),
    1,
  )
  const index = loadEvidence(home, 'sess')
  assert.equal(index.size, 1)
  const session = {
    id: 'sess',
    eventAt: (seq) => (seq === 3 ? { seq: 3, type: 'message/assistant' } : undefined),
    deriveEventMessage: () => message,
  }
  const { store, access } = sessionStore(session, index, (value) => value.content[0].text)
  assert.equal(JSON.parse(read(store, access, 3).content).content[0].text, quote)

  // 5. The judgment survives outside the checkpoint text, with its provenance.
  const understanding = new UnderstandingStore({ file: join(home, 'wsc', 'understanding', 'sess.jsonl') })
  for (const fact of operation.package.judgments) {
    understanding.write(
      {
        text: fact.text,
        kind: 'judgment',
        sources: fact.sources,
        scope: { session: 'sess', shadowedSeqs: [3] },
      },
      { producer: 'selection' },
    )
  }
  const reloaded = new UnderstandingStore({ file: understanding.file })
  assert.equal(reloaded.all().length, 1)
  assert.deepEqual(reloaded.all()[0].sources, ['s1'])
  assert.deepEqual(reloaded.all()[0].scope.shadowedSeqs, [3])
  assert.equal(reloaded.resolve(reloaded.all()[0].ref).text, 'retry errors surface after the first commit')

  // 6. The exported object is leased and re-checked before installation.
  const io = new ResourceIO()
  const exported = join(home, 'wsc', 'evidence', 'sess', '3.json')
  io.writeOnce(exported, Buffer.from(canonicalJson(message)))
  const package_ = {
    evidence: { 3: { file_path: exported, sha256: sha256Hex(canonicalJson(message)) } },
  }
  const lease = io.lease(package_)
  lease.verify()
  checkEvidence(io, package_)
  writeFileSync(exported, '{"tampered":true}')
  assert.throws(() => checkEvidence(io, package_), /exported_source_changed/)
  assert.throws(() => lease.verify(), /evidence_resource_changed/)
})

test('integration: the payload carries the second working set for a read and an edit', () => {
  // The engine forwards `settings.workingset` into the builder unchanged, so
  // this exercises the whole chain a live compaction runs: projection of the
  // tool blocks, the working-set builder, and the rendered checkpoint the model
  // receives. It is the regression line for "the file state stopped arriving".
  const call = (id, name, args) => ({ type: 'tool-call', id, name, arguments: JSON.stringify(args) })
  const messages = [
    { role: 'user', source: { kind: 'user' }, content: text('Rename the resolver.') },
    { role: 'assistant', content: [{ type: 'text', text: 'Reading it.' }, call('c1', 'read', { path: 'src/planner.js' })] },
    {
      role: 'user',
      toolCallId: 'c1',
      content: [{ type: 'text', text: '<path>src/planner.js</path>\n<content>\nline one\nline two\n</content>' }],
    },
    { role: 'assistant', content: [{ type: 'text', text: 'Renaming.' }, call('c2', 'edit', { path: 'src/planner.js', old_string: 'line one', new_string: 'line 1' })] },
  ]

  const built = buildCheckpoint({ messages }, { workingset: { version: 2, maxFiles: 4, capChars: 600, sectionCap: 2000 } })

  assert.ok(built.text.includes('## Working set'), 'the payload has a working set section')
  assert.match(built.text, /read #\d+/, 'the section is dated by the read it came from')
  assert.match(built.text, /src\/planner\.js/, 'the file the region read is named')
  assert.match(built.text, /line two/, 'the body the model last saw is still there')
  assert.match(built.text, /edited #\d+/, 'the edit is carried as a delta, not a second copy of the body')
})
