import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { existsSync } from 'node:fs';

const root = process.env.MINI_BUILD_ROOT ?? process.cwd();
const loaderPath = join(root, 'lib', 'loader.js');

test('loader module exists at the new path', () => {
  assert.equal(existsSync(loaderPath), true);
});

test('old config module is gone', () => {
  assert.equal(existsSync(join(root, 'lib', 'config.js')), false);
});

test('loadConfig is exported and still validates', async () => {
  const { loadConfig } = await import(pathToFileURL(loaderPath).href);
  assert.equal(typeof loadConfig, 'function');
  assert.deepEqual(loadConfig({ host: 'h', port: 80 }), { host: 'h', port: 80, retries: 2 });
  assert.throws(() => loadConfig({ host: '', port: 80 }), TypeError);
  assert.throws(() => loadConfig({ host: 'h', port: 70000 }), RangeError);
});

test('createApp uses the renamed loader', async () => {
  const { createApp } = await import(pathToFileURL(join(root, 'lib', 'app.js')).href);
  assert.deepEqual(createApp({ host: 'localhost', port: 8080 }), {
    config: { host: 'localhost', port: 8080, retries: 2 },
    url: 'http://localhost:8080',
    mode: 'retry',
  });
});

test('no compatibility re-export of the old name', async () => {
  const app = await import(pathToFileURL(join(root, 'lib', 'app.js')).href);
  assert.equal('parseConfig' in app, false);
});
