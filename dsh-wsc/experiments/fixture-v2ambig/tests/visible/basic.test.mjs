import test from 'node:test';
import assert from 'node:assert/strict';
import { discountFor } from '../../src/pricing.js';

test('no discount', () => {
  assert.equal(discountFor(1000, 'none'), 1000);
});

test('rejects an unknown tier', () => {
  assert.throws(() => discountFor(1000, 'platinum'), TypeError);
});
