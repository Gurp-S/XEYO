import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { loadSettings } from '../../src/settings.js';

test('normalises version 1', () => {
  assert.deepEqual(loadSettings({ db: { host: 'localhost', port: 5432 } }), {
    database: { host: 'localhost', port: 5432, ssl: false },
  });
});

test('rejects a bad port', () => {
  assert.throws(() => loadSettings({ db: { host: 'localhost', port: 0 } }), RangeError);
});

test('accepts version 2 as-is', () => {
  assert.deepEqual(loadSettings({ database: { host: 'db.internal', port: 6543, ssl: true } }), {
    database: { host: 'db.internal', port: 6543, ssl: true },
  });
});

test('defaults version 2 ssl to false', () => {
  assert.deepEqual(loadSettings({ database: { host: 'db.internal', port: 6543 } }), {
    database: { host: 'db.internal', port: 6543, ssl: false },
  });
});

test('rejects ssl in version 1', () => {
  assert.throws(() => loadSettings({ db: { host: 'localhost', port: 5432, ssl: true } }), TypeError);
  assert.throws(() => loadSettings({ db: { host: 'localhost', port: 5432, ssl: false } }), TypeError);
});

test('rejects a file carrying both db and database', () => {
  assert.throws(
    () =>
      loadSettings({
        db: { host: 'localhost', port: 5432 },
        database: { host: 'db.internal', port: 6543 },
      }),
    TypeError,
  );
});

test('rejects unknown top-level keys', () => {
  assert.throws(() => loadSettings({ db: { host: 'localhost', port: 5432 }, extra: true }), TypeError);
  assert.throws(() => loadSettings({ database: { host: 'db.internal', port: 6543 }, db2: {} }), TypeError);
});

test('rejects shapes that are not settings', () => {
  assert.throws(() => loadSettings(null), TypeError);
  assert.throws(() => loadSettings({}), TypeError);
  assert.throws(() => loadSettings({ database: null }), TypeError);
  assert.throws(() => loadSettings({ database: { host: '', port: 6543 } }), TypeError);
  assert.throws(() => loadSettings({ database: { host: 'db.internal', port: 70000 } }), RangeError);
  assert.throws(() => loadSettings({ database: { host: 'db.internal', port: 6543, ssl: 'yes' } }), TypeError);
});

test('settings.json keeps loading', async () => {
  const raw = JSON.parse(await readFile(new URL('../../settings.json', import.meta.url), 'utf8'));
  assert.deepEqual(loadSettings(raw), { database: { host: 'localhost', port: 5432, ssl: false } });
});
