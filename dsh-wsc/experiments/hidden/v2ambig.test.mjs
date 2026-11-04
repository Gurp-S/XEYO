import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';

const root = process.env.MINI_BUILD_ROOT ?? process.cwd();
const { discountFor } = await import(pathToFileURL(join(root, 'src', 'pricing.js')).href);

test('silver rounds half up', () => {
  assert.equal(discountFor(999, 'silver'), 949);
});

test('gold rounds half up', () => {
  assert.equal(discountFor(999, 'gold'), 899);
});

test('exact cents stay exact', () => {
  assert.equal(discountFor(1000, 'silver'), 950);
  assert.equal(discountFor(0, 'gold'), 0);
});

test('unknown tier still throws', () => {
  assert.throws(() => discountFor(1000, 'platinum'), TypeError);
});

test('checkoutTotal still composes', async () => {
  const { checkoutTotal } = await import(pathToFileURL(join(root, 'src', 'cart.js')).href);
  assert.equal(checkoutTotal([{ priceCents: 333, quantity: 3 }], 'gold'), 899);
});

test('status says the current version was not verified before this session', () => {
  const status = readFileSync(join(root, 'STATUS.md'), 'utf8');
  const verdict = /VERIFIED_BEFORE_SESSION:\s*(\S+)/i.exec(status);
  assert.ok(verdict, 'STATUS.md missing VERIFIED_BEFORE_SESSION');
  assert.equal(verdict[1].toLowerCase().replace(/[^a-z]/g, ''), 'no');
});

test('evidence line comes from the log', () => {
  const status = readFileSync(join(root, 'STATUS.md'), 'utf8');
  const evidence = /EVIDENCE:\s*(.+)/i.exec(status);
  assert.ok(evidence, 'STATUS.md missing EVIDENCE');
  assert.match(evidence[1], /v2|untested|no run|nothing has been run/i);
});
