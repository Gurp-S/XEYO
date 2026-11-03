import test from 'node:test';
import assert from 'node:assert/strict';
import { slugify, slugifyAll } from '../../src/slug.js';

test('lowercases and dashes spaces', () => {
  assert.equal(slugify('Hello World'), 'hello-world');
});

test('drops punctuation', () => {
  assert.equal(slugify('Hello, World!'), 'hello-world');
});

test('maps over a list', () => {
  assert.deepEqual(slugifyAll(['A B', 'C D']), ['a-b', 'c-d']);
});
