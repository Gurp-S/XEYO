import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const run = promisify(execFile);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-visible-'));
  await cp(repoRoot, dir, {
    recursive: true,
    filter: (src) => !/[\\/](out|node_modules)([\\/]|$)/.test(src) && !src.endsWith('build-manifest.json'),
  });
  return dir;
}

async function build(dir) {
  const { stdout } = await run(process.execPath, ['bin/build.js', '--json'], { cwd: dir });
  return JSON.parse(stdout);
}

test('build emits outputs and a v2 manifest', async () => {
  const dir = await project();
  try {
    await build(dir);
    assert.match(await readFile(path.join(dir, 'out/a.js'), 'utf8'), /\/\/# build [0-9a-f]{8}/);
    assert.match(await readFile(path.join(dir, 'out/style.css'), 'utf8'), /url\(img\.[0-9a-f]{8}\.png\)/);
    const manifest = JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
    assert.equal(manifest.version, 2);
    assert.ok(manifest.files['a.js']);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a second build with no source change skips every file', async () => {
  const dir = await project();
  try {
    await build(dir);
    const second = await build(dir);
    assert.equal(second.built.length, 0);
    assert.ok(second.skipped.length > 0);
    assert.ok((await stat(path.join(dir, 'out/a.js'))).isFile());
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
