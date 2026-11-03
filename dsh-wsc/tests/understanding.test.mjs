import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { UnderstandingStore } from '../lib/understanding.js'

const store = () => new UnderstandingStore({ file: join(mkdtempSync(join(tmpdir(), 'wsc-und-')), 'u.jsonl') })

test('understanding: a first write needs no expected revision and is revision 1', () => {
  const s = store()
  const record = s.write({ text: 'the lease is identity-based', kind: 'constraint', sources: ['12'] }, { producer: 'selection' })
  assert.equal(record.revision, 1)
  assert.equal(record.ref, `${record.id}@1`)
  assert.equal(record.previous, null)
  assert.equal(record.producer, 'selection')
  assert.equal(s.all().length, 1)
  assert.equal(s.epoch(), 1)
})

test('understanding: a revision is a compare-and-swap against the stored one', () => {
  const s = store()
  const first = s.write({ text: 'a', kind: 'fact', sources: ['1'] }, { producer: 'selection' })
  assert.throws(() => s.write({ id: first.id, text: 'b', kind: 'fact' }, { producer: 'selection' }), /understanding_revision_conflict/)
  const second = s.write({ id: first.id, text: 'b', kind: 'fact', expectedRevision: 1 }, { producer: 'selection' })
  assert.equal(second.revision, 2)
  assert.equal(second.previous, `${first.id}@1`)
  assert.equal(s.all().length, 1, 'only the newest revision is current')
  assert.equal(s.all()[0].text, 'b')
  assert.equal(s.resolve(`${first.id}@1`).text, 'a')
  assert.throws(() => s.resolve(`${first.id}@9`), /understanding_reference_missing/)
})

test('understanding: records replay from the journal after a restart', () => {
  const s = store()
  const first = s.write({ text: 'a', kind: 'fact', sources: ['1'], scope: { file: 'x.js' } }, { producer: 'selection' })
  const reloaded = new UnderstandingStore({ file: s.file })
  assert.deepEqual(reloaded.all(), [first])
  assert.equal(reloaded.epoch(), 1)
  assert.equal(reloaded.all()[0].scope.file, 'x.js')
  assert.equal(readFileSync(s.file, 'utf8').trim().split('\n').length, 1)
})

test('understanding: empty text, a bad producer and an unknown source are refused', () => {
  const s = store()
  assert.throws(() => s.write({ text: '   ', kind: 'fact' }, { producer: 'selection' }), /understanding_text_empty/)
  assert.throws(() => s.write({ text: 'a', kind: 'fact' }, { producer: 'bad producer' }), /understanding_producer_invalid/)
  assert.throws(() => s.write({ text: 'a', kind: 'fact', sources: ['99'] }, { producer: 'selection', allowedSources: ['1'] }), /understanding_source_missing/)
  assert.throws(() => s.write({ text: 'a', kind: 'fact', expectedRevision: 0 }, { producer: 'selection' }), /understanding_revision_invalid/)
  assert.throws(() => s.write({ text: 'a', kind: 'fact', scope: 'x' }, { producer: 'selection' }), /invalid_understanding_scope/)
  assert.equal(s.epoch(), 0, 'a refused write appends nothing')
})
