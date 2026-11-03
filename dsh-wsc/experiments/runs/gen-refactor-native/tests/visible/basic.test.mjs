import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../../lib/app.js';
import { loadConfig } from '../../lib/loader.js';

test('builds a descriptor', () => {
  assert.deepEqual(createApp({ host: 'localhost', port: 8080 }), {
    config: { host: 'localhost', port: 8080, retries: 2 },
    url: 'http://localhost:8080',
    mode: 'retry',
  });
});

test('rejects a bad port', () => {
  assert.throws(() => createApp({ host: 'localhost', port: 0 }), RangeError);
});

test('loadConfig validates and normalises', () => {
  assert.deepEqual(loadConfig({ host: 'localhost', port: 8080 }), { host: 'localhost', port: 8080, retries: 2 });
  assert.throws(() => loadConfig(null), TypeError);
});

test('the old config module is gone', async () => {
  await assert.rejects(import('../../lib/config.js'));
});
