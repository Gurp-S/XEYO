import assert from 'node:assert/strict';
import { test } from 'node:test';

import { count, top } from '../../lib/count.js';
import { tokenize } from '../../lib/tokenize.js';

test('punctuation is not part of a word, and case is folded', () => {
  assert.deepEqual(tokenize('Hello, world! Hello.'), ['hello', 'world', 'hello']);
});

test('an apostrophe stays inside the word', () => {
  assert.deepEqual(tokenize("Don't stop"), ["don't", 'stop']);
});

test('ties sort by word', () => {
  assert.deepEqual(top(count('b a b a c')), [
    ['a', 2],
    ['b', 2],
    ['c', 1],
  ]);
});
