import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.env.MINI_BUILD_ROOT ?? process.cwd();
const { slugify, slugifyAll } = await import(pathToFileURL(join(root, 'src', 'slug.js')).href);

test('collapses runs of separators', () => {
  assert.equal(slugify('a   b'), 'a-b');
  assert.equal(slugify('a---b'), 'a-b');
});

test('trims separators at both ends', () => {
  assert.equal(slugify('--x--'), 'x');
  assert.equal(slugify('  Hello  '), 'hello');
});

test('transliterates accents', () => {
  assert.equal(slugify('Über Café'), 'uber-cafe');
});

test('treats underscores and symbols as separators', () => {
  assert.equal(slugify('A_B'), 'a-b');
  assert.equal(slugify('a/b'), 'a-b');
});

test('empty and separator-only input', () => {
  assert.equal(slugify(''), '');
  assert.equal(slugify('   '), '');
  assert.equal(slugify('!!!'), '');
});

test('digits survive', () => {
  assert.equal(slugify('Node 20 ESM'), 'node-20-esm');
});

test('list helper keeps the same rules', () => {
  assert.deepEqual(slugifyAll(['Über  Café', '--x--']), ['uber-cafe', 'x']);
});
