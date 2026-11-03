import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  canonicalJson,
  digest,
  read,
  recordEvidence,
  loadEvidence,
  writeOnce,
  sameBytes,
  linkLike,
  exportSources,
  sha256Bytes,
  sessionStore,
} from '../lib/evidence.js'

const payload = { role: 'assistant', content: [{ type: 'text', text: 'the parser must reject an empty path' }] }
const row = { seq: 7, kind: 'message', payload, text: 'the parser must reject an empty path', digest: digest(payload), observedAt: 't0' }
const store = { sessionId: 's1', sourceRow: (id) => (String(id) === '7' ? row : undefined) }
const allow = () => true
const deny = () => false

test('evidence: canonical JSON is sorted, compact and non-ASCII preserving', () => {
  assert.equal(canonicalJson({ b: 1, a: [true, null, '中'] }), '{"a":[true,null,"中"],"b":1}')
  assert.equal(digest({ b: 1, a: 2 }), digest({ a: 2, b: 1 }), 'key order does not change the digest')
  assert.throws(() => canonicalJson({ n: Number.NaN }), /invalid_json_value/)
})

test('evidence: an authorized read returns exact bytes and both hashes', () => {
  const result = read(store, allow, 7)
  assert.equal(result.content, canonicalJson(payload))
  assert.equal(result.complete, true)
  assert.equal(result.total_bytes, Buffer.byteLength(canonicalJson(payload), 'utf8'))
  assert.equal(result.object_sha256, sha256Bytes(Buffer.from(canonicalJson(payload), 'utf8')))
  assert.equal(result.read_sha256, result.object_sha256)
  assert.equal(result.representation, 'canonical_native_json_value')
  assert.equal(result.observed_at, 't0')
})

test('evidence: offsets and limits are bytes, and a chunk is not complete', () => {
  const whole = Buffer.from(canonicalJson(payload), 'utf8')
  const result = read(store, allow, 7, { offset: 5, limit: 10 })
  assert.equal(result.content, whole.subarray(5, 15).toString('utf8'))
  assert.equal(result.length, 10)
  assert.equal(result.complete, false)
  assert.equal(result.read_sha256, sha256Bytes(whole.subarray(5, 15)))
  assert.equal(result.object_sha256, sha256Bytes(whole))
})

test('evidence: an unauthorized read is refused without revealing bytes', () => {
  assert.throws(() => read(store, deny, 7), (error) => {
    assert.equal(error.message, 'Permission denied: source')
    assert.ok(!String(error.message).includes('parser'), 'the refusal carries no content')
    return true
  })
})

test('evidence: a digest that no longer matches the stored evidence is refused', () => {
  const tampered = { ...store, sourceRow: () => ({ ...row, payload: { ...payload, content: [] } }) }
  assert.throws(() => read(tampered, allow, 7), /source_integrity_mismatch/)
  assert.throws(() => read(store, allow, 'missing'), /source_unavailable/)
  assert.throws(() => read(store, allow, 7, { offset: -1 }), /invalid_offset/)
  assert.throws(() => read(store, allow, 7, { limit: 1.5 }), /invalid_limit/)
})

test('evidence: the index records a shadowed observation and reloads it', () => {
  const home = mkdtempSync(join(tmpdir(), 'wsc-evidence-'))
  assert.equal(recordEvidence(home, 's/1', [{ seq: 7, digest: row.digest, bytes: 10, observedAt: 't0' }]), 1)
  recordEvidence(home, 's/1', [{ seq: 7, digest: 'newer', bytes: 12 }])
  recordEvidence(home, 's/1', [{ seq: 8, digest: 'd8' }])
  const index = loadEvidence(home, 's/1')
  assert.equal(index.size, 2)
  assert.equal(index.get(7).digest, 'newer', 'the newest row wins')
  assert.equal(loadEvidence(home, 'other').size, 0, 'a session has its own index')
})

test('evidence: a write-once object is never replaced or followed', () => {
  const dir = mkdtempSync(join(tmpdir(), 'wsc-write-'))
  const file = join(dir, 'obj.json')
  writeOnce(file, Buffer.from('{"a":1}'))
  writeOnce(file, Buffer.from('{"a":1}'), { sync: false })
  assert.equal(readFileSync(file, 'utf8'), '{"a":1}')
  assert.throws(() => writeOnce(file, Buffer.from('{"a":2}')), /evidence_object_conflict/)
  assert.equal(sameBytes(file, Buffer.from('{"a":1}')), true)
  assert.equal(sameBytes(file, Buffer.from('{"a":1} ')), false)
})

test('evidence: a link leaf is refused rather than followed', () => {
  const dir = mkdtempSync(join(tmpdir(), 'wsc-link-'))
  const target = join(dir, 'target.json')
  writeFileSync(target, '{"a":1}')
  const link = join(dir, 'link.json')
  try {
    symlinkSync(target, link, 'file')
  } catch {
    return // creating a link needs a privilege this environment may not grant
  }
  assert.equal(linkLike(link), true)
  assert.throws(() => writeOnce(link, Buffer.from('{"a":1}')), /evidence_path_symlink/)
})

test('evidence: a session store reads only the seqs its index recorded', () => {
  const message = { role: 'user', content: [{ type: 'text', text: 'hello' }] }
  const session = {
    id: 's2',
    eventAt: (seq) => (seq === 3 ? { seq: 3, type: 'message/user' } : undefined),
    deriveEventMessage: () => message,
  }
  const index = new Map([[3, { seq: 3, digest: digest(message) }]])
  const { store, access } = sessionStore(session, index, (m) => m.content[0].text)
  assert.equal(read(store, access, 3).content, canonicalJson(message))
  assert.throws(() => read(store, access, 4), /Permission denied: source/)

  const other = new Map([[3, { seq: 3, digest: 'not-this-object' }]])
  const stale = sessionStore(session, other, (m) => m.content[0].text)
  assert.throws(() => read(stale.store, stale.access, 3), /source_integrity_mismatch/)
})

test('evidence: export writes content-addressed objects with a readable sibling', () => {
  const dir = mkdtempSync(join(tmpdir(), 'wsc-export-'))
  const locators = exportSources(store, allow, [7], dir)
  const locator = locators[7]
  assert.equal(locator.sha256, digest(payload))
  assert.ok(locator.file_path.endsWith(`${digest(payload)}.json`))
  assert.equal(readFileSync(locator.file_path, 'utf8'), canonicalJson(payload))
  assert.ok(locator.readable_path.endsWith(`${locator.readable_sha256}.txt`))
  assert.equal(readFileSync(locator.readable_path, 'utf8'), 'the parser must reject an empty path')
})
