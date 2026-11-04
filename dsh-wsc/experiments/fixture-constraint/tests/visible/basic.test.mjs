import test from 'node:test';
import assert from 'node:assert/strict';
import { listUsers } from '../../src/api.js';

test('lists users', () => {
  assert.equal(listUsers().length, 2);
});
