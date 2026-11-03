import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  textAt,
  sliceCodepoints,
  codepointLength,
  fragmentOffsets,
  resolveExcerpt,
  ranges,
  sha256Hex,
} from '../lib/excerpts.js'

const payload = { content: [{ type: 'text', text: 'the parser must reject an empty path' }] }
const known = new Map([
  ['m1', { kind: 'message', payload, text: 'the parser must reject an empty path', observedAt: 't0', callId: 'c1' }],
  ['m2', { kind: 'opaque', payload: { secret: 'x' } }],
])

test('excerpts: a payload path addresses nested text', () => {
  assert.equal(textAt(payload, ['content', 0, 'text']), 'the parser must reject an empty path')
  assert.throws(() => textAt(payload, []), /excerpt_value_not_text/, 'the payload itself is not text')
})

test('excerpts: a null step decodes a JSON string', () => {
  const nested = { body: JSON.stringify({ inner: 'decoded value' }) }
  assert.equal(textAt(nested, ['body', null, 'inner']), 'decoded value')
})

test('excerpts: unavailable addresses fail with the WSC codes', () => {
  assert.throws(() => textAt(payload, ['content', 9, 'text']), /excerpt_index_unavailable/)
  assert.throws(() => textAt(payload, ['missing']), /excerpt_key_unavailable/)
  assert.throws(() => textAt({ n: 42 }, ['n']), /excerpt_value_not_text/)
  assert.throws(() => textAt({ j: 'not json' }, ['j', null]), /excerpt_json_unavailable/)
})

test('excerpts: a span resolves to exact text and its digest', () => {
  const resolved = resolveExcerpt(known, { source: 'm1', path: ['content', 0, 'text'], start: 4, end: 10 })
  assert.equal(resolved.text, 'parser')
  assert.equal(resolved.textSha256, sha256Hex('parser'))
  assert.equal(resolved.sourceKind, 'message')
  assert.equal(resolved.callId, 'c1')
})

test('excerpts: a claimed digest that does not match the bytes is refused', () => {
  assert.throws(
    () => resolveExcerpt(known, { source: 'm1', path: ['content', 0, 'text'], start: 4, end: 10, sha256: sha256Hex('other') }),
    /excerpt_content_mismatch/,
  )
  assert.doesNotThrow(() =>
    resolveExcerpt(known, { source: 'm1', path: ['content', 0, 'text'], start: 4, end: 10, sha256: sha256Hex('parser') }),
  )
})

test('excerpts: an empty or inverted range is refused', () => {
  assert.throws(() => resolveExcerpt(known, { source: 'm1', path: ['content', 0, 'text'], start: 6, end: 6 }), /excerpt_range_invalid/)
  assert.throws(() => resolveExcerpt(known, { source: 'm1', path: ['content', 0, 'text'], start: 9, end: 3 }), /excerpt_range_invalid/)
  assert.throws(() => resolveExcerpt(known, { source: 'm1', path: ['content', 0, 'text'], start: 0, end: 999 }), /excerpt_range_invalid/)
})

test('excerpts: an exact fragment resolves only when it is unique', () => {
  const resolved = resolveExcerpt(known, { source: 'm1', path: ['content', 0, 'text'], fragment: 'empty path' })
  assert.equal(resolved.text, 'empty path')
  assert.equal(resolved.start, 26)
  assert.equal(resolved.end, 36)
  assert.throws(() => resolveExcerpt(known, { source: 'm1', path: ['content', 0, 'text'], fragment: 'absent text' }), /excerpt_fragment_missing/)
  const repeated = new Map([['r', { kind: 'message', payload: { t: 'ab ab' } }]])
  assert.throws(() => resolveExcerpt(repeated, { source: 'r', path: ['t'], fragment: 'ab' }), /excerpt_fragment_ambiguous/)
})

test('excerpts: an unknown or opaque source is refused', () => {
  assert.throws(() => resolveExcerpt(known, { source: 'nope', start: 0, end: 1 }), /excerpt_source_missing/)
  assert.throws(() => resolveExcerpt(known, { source: 'm2', path: ['secret'], start: 0, end: 1 }), /opaque_excerpt_unavailable/)
})

test('excerpts: public text takes no payload path', () => {
  const publicOnly = new Map([['p', { kind: 'public', text: 'public observation' }]])
  const resolved = resolveExcerpt(publicOnly, { source: 'p', basis: 'public_text', start: 0, end: 6 })
  assert.equal(resolved.text, 'public')
  assert.throws(() => resolveExcerpt(publicOnly, { source: 'p', basis: 'public_text', path: ['x'], start: 0, end: 1 }), /public_text_excerpt_path_invalid/)
  assert.throws(() => resolveExcerpt(publicOnly, { source: 'p', basis: 'raw', start: 0, end: 1 }), /excerpt_basis_invalid/)
})

test('excerpts: offsets count code points, not UTF-16 units', () => {
  const astral = 'a😀b'
  assert.equal(codepointLength(astral), 3)
  assert.equal(sliceCodepoints(astral, 1, 3), '😀b')
  assert.equal(astral.length, 4, 'the JS string is longer than the code point count')
  assert.deepEqual(fragmentOffsets(astral, 'b'), [2])
})

test('excerpts: fixed partitions cover the text exactly once', () => {
  const text = 'abcdefghij'
  const parts = ranges(text, 4)
  assert.deepEqual(parts.map((part) => part.text), ['abcd', 'efgh', 'ij'])
  assert.equal(parts.map((part) => part.text).join(''), text)
})

test('excerpts: word partitions do not split an identifier', () => {
  const text = 'read the parser_v2.py file now'
  const parts = ranges(text, 12, { policy: 'word' })
  assert.equal(parts.map((part) => part.text).join(''), text)
  assert.ok(parts.every((part) => part.text.length <= 12))
  assert.ok(parts.some((part) => part.text.includes('parser_v2.py')), 'the identifier stays whole')
})

test('excerpts: an over-limit uninterrupted run still respects the bound', () => {
  const text = 'x'.repeat(30)
  const parts = ranges(text, 10, { policy: 'word' })
  assert.deepEqual(parts.map((part) => part.text.length), [10, 10, 10])
})

test('excerpts: invalid partition arguments are refused', () => {
  assert.throws(() => ranges('abc', 0), /span_size_invalid/)
  assert.throws(() => ranges('abc', 2, { policy: 'sentence' }), /span_boundary_policy_invalid/)
})
