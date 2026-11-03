import test from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../../lib/app.js';

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
