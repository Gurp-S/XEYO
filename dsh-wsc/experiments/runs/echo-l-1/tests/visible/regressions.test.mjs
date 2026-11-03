import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdtemp, open, readFile, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const run = promisify(execFile);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-regress-'));
  await cp(repoRoot, dir, {
    recursive: true,
    filter: (src) => !/[\\/](out|node_modules)([\\/]|$)/.test(src) && !src.endsWith('build-manifest.json'),
  });
  return dir;
}

async function build(dir, extra = []) {
  const { stdout } = await run(process.execPath, ['bin/build.js', '--json', ...extra], { cwd: dir });
  return JSON.parse(stdout);
}

async function manifest(dir) {
  return JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
}

async function outputs(dir) {
  const { readdir } = await import('node:fs/promises');
  const entries = await readdir(path.join(dir, 'out'), { withFileTypes: true });
  const map = {};
  for (const entry of entries) {
    if (entry.isFile()) map[entry.name] = (await readFile(path.join(dir, 'out', entry.name))).toString('base64');
  }
  return map;
}

test('a stylesheet is rebuilt when a url(...) asset changes', async () => {
  const dir = await project();
  try {
    await build(dir);
    const before = (await manifest(dir)).files['style.css'];
    await writeFile(path.join(dir, 'src/img.png'), Buffer.from('not the same bytes'));
    const report = await build(dir);
    assert.ok(report.built.includes('style.css'), 'stylesheet rebuilt');
    const after = (await manifest(dir)).files['style.css'];
    assert.notEqual(after.deps['img.png'], before.deps['img.png']);
    const css = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    assert.match(css, /url\(img\.[0-9a-f]{8}\.png\)/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a json file is rebuilt when its extends base changes', async () => {
  const dir = await project();
  try {
    await build(dir);
    await writeFile(path.join(dir, 'src/base.json'), `${JSON.stringify({ name: 'base', level: 2 }, null, 2)}\n`);
    const report = await build(dir);
    assert.ok(report.built.includes('data.json'));
    const data = JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8'));
    assert.equal(data.level, 2);
    assert.equal(data.name, 'demo');
    assert.equal(data.extends, undefined);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('rewriting a source without changing its mtime still rebuilds', async () => {
  const dir = await project();
  try {
    await build(dir);
    const file = path.join(dir, 'src/b.js');
    const before = await stat(file);
    await writeFile(file, "export const b = 'B2';\n");
    await utimes(file, before.atime, before.mtime);
    const after = await stat(file);
    assert.equal(after.mtimeMs, before.mtimeMs, 'mtime is unchanged');
    const report = await build(dir);
    assert.ok(report.built.includes('b.js'));
    const out = await readFile(path.join(dir, 'out/b.js'), 'utf8');
    assert.match(out, /B2/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('deleting a source removes its output and its manifest entry', async () => {
  const dir = await project();
  try {
    await build(dir);
    await rm(path.join(dir, 'src/b.js'));
    const report = await build(dir);
    assert.ok(report.removed.includes('b.js'));
    await assert.rejects(stat(path.join(dir, 'out/b.js')));
    assert.equal((await manifest(dir)).files['b.js'], undefined);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a manifest naming missing outputs heals itself', async () => {
  const dir = await project();
  try {
    await build(dir);
    await rm(path.join(dir, 'out/a.js'));
    const report = await build(dir);
    assert.ok(report.built.includes('a.js'));
    assert.ok((await stat(path.join(dir, 'out/a.js'))).isFile());
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a truncated manifest does not crash the next build', async () => {
  const dir = await project();
  try {
    await writeFile(path.join(dir, 'build-manifest.json'), '{"version": 2, "files": {"a.js": ');
    const report = await build(dir);
    assert.ok(report.built.length > 0);
    assert.equal((await manifest(dir)).version, 2);
    assert.ok((await stat(path.join(dir, 'out/a.js'))).isFile());
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--concurrency does not change the output bytes', async () => {
  const one = await project();
  const many = await project();
  try {
    await build(one, ['--concurrency', '1']);
    await build(many, ['--concurrency', '4']);
    assert.deepEqual(await outputs(one), await outputs(many));
  } finally {
    await rm(one, { recursive: true, force: true });
    await rm(many, { recursive: true, force: true });
  }
});

test('--concurrency rejects values that are not positive integers', async () => {
  const dir = await project();
  try {
    await assert.rejects(run(process.execPath, ['bin/build.js', '--concurrency', '0'], { cwd: dir }), /positive integer/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

async function waitForLog(file, pattern, timeoutMs = 20000) {
  const started = Date.now();
  let text = '';
  while (Date.now() - started < timeoutMs) {
    try {
      text = await readFile(file, 'utf8');
    } catch {
      text = '';
    }
    if (pattern.test(text)) return text;
    await delay(50);
  }
  throw new Error(`timed out waiting for ${pattern}:\n${text}`);
}

test('--watch rebuilds when a source changes', async () => {
  const dir = await project();
  const logFile = path.join(dir, 'watch.log');
  const handle = await open(logFile, 'w');
  const child = spawn(process.execPath, ['bin/build.js', '--watch'], {
    cwd: dir,
    stdio: ['ignore', handle.fd, handle.fd],
  });
  try {
    await waitForLog(logFile, /watching src for changes/);
    await waitForLog(logFile, /built \d+, skipped \d+, removed \d+/);
    await writeFile(path.join(dir, 'src/a.js'), "export const a = 'WATCHED';\n");
    await waitForLog(logFile, /built 1,/);
    assert.match(await readFile(path.join(dir, 'out/a.js'), 'utf8'), /WATCHED/);
  } finally {
    child.kill();
    await new Promise((resolve) => child.once('exit', resolve));
    await handle.close();
    await rm(dir, { recursive: true, force: true });
  }
});
