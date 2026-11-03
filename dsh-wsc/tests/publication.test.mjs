import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  checkBinding,
  confirm,
  discard,
  install,
  loadOperations,
  reconcile,
  recordOperation,
} from '../lib/publication.js'

const pkg = {
  sessionId: 's1',
  provider: 'deepseek',
  model: 'v4',
  throughSeq: 42,
  packageDigest: 'abc123',
}

const receipt = (over = {}) => ({
  operationId: 'op1',
  packageDigest: 'abc123',
  sessionId: 's1',
  provider: 'deepseek',
  model: 'v4',
  installedThrough: 42,
  receiver: 'session-log',
  evidenceAccessible: true,
  ...over,
})

const ready = () => ({ id: 'op1', state: 'ready', package: pkg })

test('publication: a bound reply confirms the operation', () => {
  const done = confirm(ready(), receipt())
  assert.equal(done.state, 'confirmed')
  assert.equal(done.receipt.operationId, 'op1')
})

test('publication: a reply bound to another package is refused', () => {
  assert.throws(() => checkBinding(ready(), receipt({ sessionId: 's2' })), /host_receipt_binding_mismatch/)
  assert.throws(() => checkBinding(ready(), receipt({ installedThrough: 41 })), /host_receipt_binding_mismatch/)
  assert.throws(() => checkBinding(ready(), receipt({ evidenceAccessible: false })), /host_receipt_binding_mismatch/)
  assert.throws(() => checkBinding(ready(), receipt({ receiver: '  ' })), /host_receipt_binding_mismatch/)
})

test('publication: confirming twice is idempotent only for the same reply', () => {
  const done = confirm(ready(), receipt())
  assert.equal(confirm(done, receipt()), done)
  assert.throws(() => confirm(done, receipt({ model: 'other' })), /host_receipt_conflict/)
})

test('publication: an install is refused unless the package is ready', () => {
  assert.throws(() => install({ ...ready(), state: 'preparing' }, { install: () => receipt() }), /installation_outcome_requires_reconciliation/)
  const { operation } = install(ready(), { install: () => receipt() })
  assert.equal(operation.state, 'confirmed')
})

test('publication: a failed host call leaves an unknown outcome, not a silent success', () => {
  const { operation, error } = install(ready(), { install: () => { throw new Error('socket closed') } })
  assert.equal(operation.state, 'unknown')
  assert.equal(error.message, 'socket closed')
})

test('publication: reconcile resolves an unknown outcome from the host log', () => {
  const unknown = { ...ready(), state: 'unknown' }
  assert.throws(() => reconcile(unknown, { lookup: () => undefined }), /host_outcome_unknown/)
  const done = reconcile(unknown, { lookup: () => receipt() })
  assert.equal(done.state, 'confirmed')
  assert.throws(() => reconcile({ ...ready(), state: 'preparing' }, { lookup: () => receipt() }), /installation_not_started/)
})

test('publication: only an unsubmitted operation can be discarded', () => {
  assert.equal(discard(ready()).state, 'cancelled')
  assert.throws(() => discard({ ...ready(), state: 'installing' }), /publication_outcome_unknown/)
})

test('publication: the journal keeps the newest row per operation', () => {
  const home = mkdtempSync(join(tmpdir(), 'wsc-ops-'))
  recordOperation(home, 's1', { id: 'op1', state: 'ready' })
  recordOperation(home, 's1', { id: 'op1', state: 'confirmed' })
  recordOperation(home, 's1', { id: 'op2', state: 'unknown' })
  const operations = loadOperations(home, 's1')
  assert.equal(operations.size, 2)
  assert.equal(operations.get('op1').state, 'confirmed')
  assert.equal(loadOperations(home, 'other').size, 0)
})
