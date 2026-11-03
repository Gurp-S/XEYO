import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtempSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { ResourceIO, checkEvidence, collectPaths } from '../lib/resources.js'

const temp = () => mkdtempSync(join(tmpdir(), 'wsc-res-'))
const sha = (bytes) => createHash('sha256').update(bytes).digest('hex')

test('resources: equal compares in bounded chunks and refuses a link leaf', () => {
  const io = new ResourceIO({ chunkBytes: 4 })
  const dir = temp()
  const file = join(dir, 'a.json')
  writeFileSync(file, 'abcdefghij')
  assert.equal(io.equal(file, Buffer.from('abcdefghij')), true)
  assert.equal(io.equal(file, Buffer.from('abcdefghiX')), false)
  assert.equal(io.equal(file, Buffer.from('abc')), false)
  const link = join(dir, 'link.json')
  try {
    symlinkSync(file, link, 'file')
  } catch {
    return
  }
  assert.throws(() => io.equal(link, Buffer.from('abcdefghij')), /evidence_path_symlink/)
})

test('resources: digest is bounded by bytes and by deadline', () => {
  const io = new ResourceIO({ chunkBytes: 3 })
  const dir = temp()
  const file = join(dir, 'b.bin')
  writeFileSync(file, 'abcdef')
  assert.equal(io.digest(file), sha('abcdef'))
  assert.equal(io.digest(file, { maxBytes: 6 }), sha('abcdef'))
  assert.throws(() => io.digest(file, { maxBytes: 5 }), /reference_resource_changed/)
  assert.throws(() => io.digest(file, { deadline: Date.now() - 1 }), /resource_read_deadline_exceeded/)
  assert.throws(() => io.digest(file, { maxBytes: -1 }), /resource_read_budget_invalid/)
})

test('resources: readBounded returns at most the budget', () => {
  const io = new ResourceIO({ chunkBytes: 2 })
  const dir = temp()
  const file = join(dir, 'c.bin')
  writeFileSync(file, 'abcdef')
  assert.equal(io.readBounded(file, 4).toString(), 'abcd')
  assert.equal(io.readBounded(file, 0).length, 0)
  assert.equal(io.readBounded(file, 99).toString(), 'abcdef')
})

test('resources: writeOnce never replaces an existing object', () => {
  const io = new ResourceIO()
  const dir = temp()
  const file = join(dir, 'obj.json')
  io.writeOnce(file, Buffer.from('{"a":1}'))
  io.writeOnce(file, Buffer.from('{"a":1}'))
  assert.equal(readFileSync(file, 'utf8'), '{"a":1}')
  assert.throws(() => io.writeOnce(file, Buffer.from('{"a":2}')), /evidence_object_conflict/)
})

test('resources: a replacement during an open is detected', () => {
  const io = new ResourceIO()
  const dir = temp()
  const file = join(dir, 'd.json')
  writeFileSync(file, 'one')
  assert.throws(
    () =>
      io.withOpened(file, () => {
        writeFileSync(file, 'two-longer')
        return 'body'
      }),
    /evidence_resource_changed/,
  )
})

test('resources: a lease records identities and fails closed when one drifts', () => {
  const io = new ResourceIO()
  const dir = temp()
  const exported = join(dir, 'objects', 'x.json')
  const source = join(dir, 'source.json')
  writeFileSync(source, '{"source":true}')
  io.writeOnce(exported, Buffer.from('{"payload":1}'))
  const pkg = {
    evidence: { 1: { file_path: exported, sha256: sha('{"payload":1}') } },
    source_index: source,
  }
  const lease = io.lease(pkg)
  assert.equal(lease.paths.length, 2)
  assert.ok(lease.directories.length >= 2, 'every parent directory is leased too')
  lease.verify()

  writeFileSync(exported, '{"payload":2}')
  assert.throws(() => lease.verify(), /evidence_resource_changed/)
  assert.throws(() => io.lease({ evidence: { 1: { file_path: join(dir, 'absent.json') } } }), /installation_resource_unavailable/)
  assert.throws(() => new ResourceIO({ maxOpenHandles: 2 }).lease(pkg), /installation_resource_budget_exhausted/)
})

test('resources: checkEvidence refuses a changed or missing export', () => {
  const io = new ResourceIO()
  const dir = temp()
  const exported = join(dir, 'e.json')
  const readable = join(dir, 'e.txt')
  const index = join(dir, 'index.json')
  io.writeOnce(exported, Buffer.from('{"payload":1}'))
  io.writeOnce(readable, Buffer.from('readable'))
  io.writeOnce(index, Buffer.from('[]'))
  const pkg = {
    evidence: {
      1: {
        file_path: exported,
        sha256: sha('{"payload":1}'),
        readable_path: readable,
        readable_sha256: sha('readable'),
      },
    },
    source_index: index,
    source_index_sha256: sha('[]'),
  }
  checkEvidence(io, pkg)

  writeFileSync(readable, 'tampered')
  assert.throws(() => checkEvidence(io, pkg), /exported_readable_changed/)
  writeFileSync(index, '[1]')
  assert.throws(() => checkEvidence(io, { ...pkg, evidence: {} }), /exported_index_changed/)
  assert.throws(() => checkEvidence(io, { evidence: { 1: { file_path: join(dir, 'gone.json'), sha256: 'x' } } }), /exported_source_unavailable/)
})

test('resources: collectPaths finds nested locators and unique bindings only', () => {
  const paths = collectPaths({
    evidence: { 1: { file_path: 'a.json', readable_path: 'a.txt' } },
    adapter: { projection_evidence: { file_path: 'p.json', sha256: 'x' } },
    source_index: 's.json',
    understanding_index: 'u.json',
    current_reference_bindings: [
      { status: 'unique_content_match', resource: 'r1.json' },
      { status: 'ambiguous', resource: 'r2.json' },
    ],
  })
  assert.equal(paths.size, 6)
  assert.ok(![...paths].some((path) => path.endsWith('r2.json')), 'a non-unique binding is not leased')
})
