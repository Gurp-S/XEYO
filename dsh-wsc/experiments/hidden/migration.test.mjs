import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.env.MINI_BUILD_ROOT ?? process.cwd();
const { loadSettings } = await import(pathToFileURL(join(root, 'src', 'settings.js')).href);

test('version 1 still normalises', () => {
  assert.deepEqual(loadSettings({ db: { host: 'localhost', port: 5432 } }), {
    database: { host: 'localhost', port: 5432, ssl: false },
  });
});

test('version 2 is accepted directly', () => {
  assert.deepEqual(loadSettings({ database: { host: 'db.internal', port: 6543 } }), {
    database: { host: 'db.internal', port: 6543, ssl: false },
  });
});

test('version 2 honours ssl', () => {
  assert.deepEqual(loadSettings({ database: { host: 'db.internal', port: 6543, ssl: true } }), {
    database: { host: 'db.internal', port: 6543, ssl: true },
  });
});

test('version 1 rejects ssl because it cannot express it', () => {
  assert.throws(() => loadSettings({ db: { host: 'localhost', port: 5432, ssl: true } }), TypeError);
});

test('mixing both shapes is rejected', () => {
  assert.throws(
    () => loadSettings({ db: { host: 'a', port: 1 }, database: { host: 'b', port: 2 } }),
    TypeError,
  );
});

test('unknown top-level keys are rejected', () => {
  assert.throws(() => loadSettings({ db: { host: 'a', port: 1 }, cache: {} }), TypeError);
});

test('validation still applies to version 2', () => {
  assert.throws(() => loadSettings({ database: { host: '', port: 1 } }), TypeError);
  assert.throws(() => loadSettings({ database: { host: 'a', port: 0 } }), RangeError);
});
