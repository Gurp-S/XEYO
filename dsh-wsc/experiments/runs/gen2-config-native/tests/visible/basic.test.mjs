import test from 'node:test';
import assert from 'node:assert/strict';
import { loadSettings } from '../../src/settings.js';

test('normalises version 1', () => {
  assert.deepEqual(loadSettings({ db: { host: 'localhost', port: 5432 } }), {
    database: { host: 'localhost', port: 5432, ssl: false },
  });
});

test('rejects a bad port', () => {
  assert.throws(() => loadSettings({ db: { host: 'localhost', port: 0 } }), RangeError);
});
