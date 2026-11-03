import test from 'node:test';
import assert from 'node:assert/strict';
import { slugify, slugifyAll } from '../../src/slug.js';

test('collapses runs of spaces and dashes to one dash', () => {
  assert.equal(slugify('a   b'), 'a-b');
  assert.equal(slugify('a---b'), 'a-b');
  assert.equal(slugify('a - _ b'), 'a-b');
});

test('trims leading and trailing separators', () => {
  assert.equal(slugify('--x--'), 'x');
  assert.equal(slugify('  x  '), 'x');
  assert.equal(slugify('-_-x-_-'), 'x');
});

test('transliterates accented letters', () => {
  assert.equal(slugify('Über Café'), 'uber-cafe');
  assert.equal(slugify('naïve résumé'), 'naive-resume');
  assert.equal(slugify('Straße'), 'strasse');
});

test('treats underscores and symbols as separators', () => {
  assert.equal(slugify('A_B'), 'a-b');
  assert.equal(slugify('a&b'), 'a-b');
  assert.equal(slugify('a.b/c'), 'a-b-c');
});

test('returns an empty string for separator-only input', () => {
  assert.equal(slugify('---'), '');
  assert.equal(slugify(' _ '), '');
  assert.equal(slugify(''), '');
});

test('keeps the documented behaviour', () => {
  assert.equal(slugify('Hello, World!'), 'hello-world');
  assert.deepEqual(slugifyAll(['A B', '--C--']), ['a-b', 'c']);
});
