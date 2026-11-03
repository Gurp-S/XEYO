import assert from 'node:assert/strict';
import { test } from 'node:test';

import { slugify, slugifyAll } from '../../src/slug.js';

// Every case below pins one rule of the separator pipeline:
//   normalize -> fold to ASCII -> collapse each non-[a-z0-9] run to one '-'
//   -> trim edge '-'. A regression in any stage breaks at least one class.

test('runs of separators collapse into a single dash', () => {
  assert.equal(slugify('a   b'), 'a-b');
  assert.equal(slugify('a - b'), 'a-b');
  assert.equal(slugify('a--b'), 'a-b');
  assert.equal(slugify('a_-_b'), 'a-b');
});

test('leading and trailing separators are trimmed', () => {
  assert.equal(slugify('--x--'), 'x');
  assert.equal(slugify('  spaced  '), 'spaced');
  assert.equal(slugify('-a-'), 'a');
});

test('accented letters are transliterated instead of dropped', () => {
  assert.equal(slugify('Über Café'), 'uber-cafe');
  assert.equal(slugify('naïve résumé'), 'naive-resume');
  // Letters with no canonical decomposition still fold via the table.
  assert.equal(slugify('Straße Øre Æble'), 'strasse-ore-aeble');
});

test('underscores and other symbols separate words', () => {
  assert.equal(slugify('A_B'), 'a-b');
  assert.equal(slugify('C++ & Rust'), 'c-rust');
});

test('input made only of separators yields an empty string', () => {
  assert.equal(slugify('---'), '');
  assert.equal(slugify('  _ - '), '');
  assert.equal(slugify(''), '');
});

test('slugifyAll applies the same rules elementwise', () => {
  assert.deepEqual(slugifyAll(['--A_B--', 'Über Café']), ['a-b', 'uber-cafe']);
});
