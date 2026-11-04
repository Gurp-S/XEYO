import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const root = process.env.MINI_BUILD_ROOT ?? process.cwd();
const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = join(dir, name);
  if (name === 'node_modules' || name === '.git') return [];
  return statSync(full).isDirectory() ? walk(full) : [full];
});

test('public module exports fetchUser', async () => {
  const module = await import(pathToFileURL(join(root, 'src', 'api.js')).href);
  assert.equal(typeof module.fetchUser, 'function');
});

test('old name is gone from the public module', async () => {
  const module = await import(pathToFileURL(join(root, 'src', 'api.js')).href);
  assert.equal('getUser' in module, false);
});

test('no caller still mentions getUser', () => {
  const offenders = walk(join(root, 'src')).concat(walk(join(root, 'bin')))
    .filter((file) => /getUser/.test(readFileSync(file, 'utf8')));
  assert.deepEqual(offenders, []);
});

test('behaviour is unchanged through the CLI', () => {
  const out = spawnSync(process.execPath, [join(root, 'bin', 'run.js'), 'u1'], { encoding: 'utf8' });
  assert.equal(out.status, 0, out.stderr);
  assert.equal(out.stdout.trim(), 'u1:Ada');
});

test('visible suite still passes', () => {
  const out = spawnSync(process.execPath, ['--test', 'tests/visible/basic.test.mjs'], { cwd: root, encoding: 'utf8' });
  assert.equal(out.status, 0, out.stdout + out.stderr);
});
