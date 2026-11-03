import test from 'node:test';
import assert from 'node:assert/strict';
import { parseCsv } from '../../src/parse.js';

test('splits rows and cells', () => {
  assert.deepEqual(parseCsv('a,b\n1,2'), [['a', 'b'], ['1', '2']]);
});

test('quoted cell keeps the separator', () => {
  assert.deepEqual(parseCsv('a,b\n"x,y",z'), [['a', 'b'], ['x,y', 'z']]);
});
