import test from 'node:test';
import assert from 'node:assert/strict';
import { parseAmount } from '../../src/money.js';
import { parseCsv, createLedger } from '../../src/ledger.js';

test('parses an amount into cents', () => {
  assert.equal(parseAmount('12.35'), 1235);
});

test('builds a ledger', () => {
  const ledger = createLedger(parseCsv('date,category,amount\n2026-10-01,food,12.35'));
  assert.equal(ledger.total, 1235);
});
