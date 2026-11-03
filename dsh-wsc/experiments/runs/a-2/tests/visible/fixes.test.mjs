import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { closeSync, existsSync, openSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const cliPath = path.join(repoRoot, 'bin', 'build.js');

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-fixes-'));
  await cp(repoRoot, dir, {
    recursive: true,
    filter: (src) => !/[\\/](out|node_modules)([\\/]|$)/.test(src) && !src.endsWith('build-manifest.json'),
  });
  return dir;
}

// Child output is captured through files rather than pipes, so the helper also
// works where stdio pipes are unavailable.
function start(dir, args) {
  const log = path.join(dir, '.build.log');
  const out = path.join(dir, '.build.out');
  const err = path.join(dir, '.build.err');
  const outFd = openSync(out, 'w');
  const errFd = openSync(err, 'w');
  const child = spawn(process.execPath, [cliPath, ...args], { cwd: dir, stdio: ['ignore', outFd, errFd] });
  closeSync(outFd);
  closeSync(errFd);
  const done = once(child, 'exit').then(([code]) => ({
    code,
    stdout: readFileSync(out, 'utf8'),
    stderr: readFileSync(err, 'utf8'),
  }));
  return { child, done, out, err, log };
}

async function cli(dir, ...args) {
  return start(dir, args).done;
}

async function build(dir, ...flags) {
  const result = await cli(dir, '--json', ...flags);
  assert.equal(result.code, 0, result.stderr);
  return JSON.parse(result.stdout);
}

async function buildFails(dir, ...flags) {
  const result = await cli(dir, '--json', ...flags);
  assert.notEqual(result.code, 0, 'build was expected to fail');
  return result;
}

async function manifestOf(dir) {
  return JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
}

async function snapshot(dir) {
  const out = {};
  for (const rel of (await readdir(dir, { recursive: true })).sort()) {
    const abs = path.join(dir, rel);
    if ((await stat(abs)).isFile()) out[rel] = (await readFile(abs)).toString('base64');
  }
  return out;
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(predicate, what, timeout = 20000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await delay(50);
  }
  throw new Error(`timed out waiting for ${what}`);
}

test('changing an asset referenced by url() rebuilds the stylesheet and retires the old asset', async () => {
  const dir = await project();
  try {
    await build(dir);
    const before = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const oldAsset = /url\((img\.[0-9a-f]{8}\.png)\)/.exec(before)[1];

    const image = await readFile(path.join(dir, 'src/img.png'));
    await writeFile(path.join(dir, 'src/img.png'), Buffer.concat([image, Buffer.from('changed')]));
    const report = await build(dir);

    assert.ok(report.built.includes('style.css'), 'stylesheet rebuilt');
    const after = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const newAsset = /url\((img\.[0-9a-f]{8}\.png)\)/.exec(after)[1];
    assert.notEqual(newAsset, oldAsset);
    assert.ok(existsSync(path.join(dir, 'out', newAsset)), 'new asset emitted');
    assert.ok(!existsSync(path.join(dir, 'out', oldAsset)), 'old asset removed');
    assert.ok((await manifestOf(dir)).files['style.css'].out.includes(newAsset));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('changing a base file pulled in through extends rebuilds the derived json', async () => {
  const dir = await project();
  try {
    await build(dir);
    await writeFile(path.join(dir, 'src/base.json'), '{ "name": "base2", "level": 2 }\n');
    const report = await build(dir);

    assert.ok(report.built.includes('data.json'), 'derived json rebuilt');
    assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')), { name: 'demo', level: 2 });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a rewrite that keeps the mtime and size still rebuilds', async () => {
  const dir = await project();
  try {
    await build(dir);
    const file = path.join(dir, 'src/b.js');
    const info = await stat(file);
    const text = await readFile(file, 'utf8');
    await writeFile(file, text.replace('B1', 'B2'));
    assert.equal((await stat(file)).size, info.size);
    await utimes(file, info.atime, info.mtime);

    const report = await build(dir);
    assert.ok(report.built.includes('b.js'), 'rewritten file rebuilt');
    assert.ok(report.built.includes('a.js'), 'dependent rebuilt');
    assert.match(await readFile(path.join(dir, 'out/b.js'), 'utf8'), /B2/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('deleting a source removes its output and its manifest entry', async () => {
  const dir = await project();
  try {
    await build(dir);
    await rm(path.join(dir, 'src/extra.js'));

    const report = await build(dir);
    assert.ok(report.removed.includes('extra.js'));
    assert.ok(!existsSync(path.join(dir, 'out/extra.js')), 'output removed');
    assert.equal((await manifestOf(dir)).files['extra.js'], undefined);
    assert.equal(report.skipped.includes('extra.js'), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a manifest naming an output that no longer exists heals itself', async () => {
  const dir = await project();
  try {
    await build(dir);
    await rm(path.join(dir, 'out/b.js'));
    const report = await build(dir);

    assert.ok(report.built.includes('b.js'));
    assert.ok(existsSync(path.join(dir, 'out/b.js')));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a truncated or corrupt manifest does not crash the next build', async () => {
  const dir = await project();
  try {
    await build(dir);
    const full = await readFile(path.join(dir, 'build-manifest.json'), 'utf8');
    await writeFile(path.join(dir, 'build-manifest.json'), full.slice(0, Math.floor(full.length / 2)));
    const truncated = await build(dir);
    assert.ok(truncated.built.includes('a.js'));

    await writeFile(path.join(dir, 'build-manifest.json'), 'not json at all');
    const corrupt = await build(dir);
    assert.ok(corrupt.built.includes('style.css'));
    assert.equal((await manifestOf(dir)).version, 2);

    // A write cut short between two top-level keys leaves valid JSON with no
    // usable entries; the build must treat it as empty instead of dereferencing
    // a missing `files` map.
    await writeFile(path.join(dir, 'build-manifest.json'), '{ "version": 2 }');
    const header = await build(dir);
    assert.ok(header.built.includes('a.js'));
    assert.equal((await manifestOf(dir)).version, 2);

    await writeFile(path.join(dir, 'build-manifest.json'), '{ "version": 2, "files": { "b.js": null } }');
    const junk = await build(dir);
    assert.ok(junk.built.includes('b.js'), 'entry without a key is rebuilt');
    assert.equal((await manifestOf(dir)).files['b.js'].key.length > 0, true);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--dry-run writes nothing at all', async () => {
  const dir = await project();
  try {
    const report = await build(dir, '--dry-run');
    assert.equal(report.dryRun, true);
    assert.ok(report.built.length > 0);
    assert.ok(!existsSync(path.join(dir, 'out')), 'no output directory');
    assert.ok(!existsSync(path.join(dir, 'build-manifest.json')), 'no manifest');

    await build(dir);
    const before = await snapshot(path.join(dir, 'out'));
    const plan = await build(dir, '--dry-run');
    assert.deepEqual(plan.built, []);
    assert.deepEqual(await snapshot(path.join(dir, 'out')), before);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--concurrency produces the same bytes as the default and rejects bad values', async () => {
  const serial = await project();
  const parallel = await project();
  try {
    await build(serial);
    await build(parallel, '--concurrency', '4');
    assert.deepEqual(await snapshot(path.join(parallel, 'out')), await snapshot(path.join(serial, 'out')));

    const zero = await buildFails(serial, '--concurrency', '0');
    assert.match(zero.stderr, /--concurrency needs a positive integer/);
    const missing = await buildFails(serial, '--concurrency');
    assert.match(missing.stderr, /--concurrency needs a value/);
  } finally {
    await rm(serial, { recursive: true, force: true });
    await rm(parallel, { recursive: true, force: true });
  }
});

test('--watch rebuilds when a source file changes', async () => {
  const dir = await project();
  const session = start(dir, ['--watch', '--json']);
  const read = (file) => {
    try {
      return readFileSync(file, 'utf8');
    } catch {
      return '';
    }
  };

  try {
    await waitFor(() => read(session.out).includes('\n'), 'the initial build');
    await waitFor(() => read(session.err).includes('watching for changes'), 'the watcher to start');

    const initial = JSON.parse(read(session.out).trim().split('\n')[0]);
    await writeFile(path.join(dir, 'src/b.js'), "export const b = 'B3';\n");
    await waitFor(() => read(session.out).trim().split('\n').length >= 2, `a rebuild (stderr: ${read(session.err)})`);

    const rebuild = JSON.parse(read(session.out).trim().split('\n')[1]);
    assert.ok(rebuild.built.includes('b.js'), 'changed file rebuilt');
    assert.ok(rebuild.built.includes('a.js'), 'dependent rebuilt');
    assert.ok(initial.built.length > 0);
    assert.match(await readFile(path.join(dir, 'out/b.js'), 'utf8'), /B3/);
  } finally {
    session.child.kill();
    await session.done.catch(() => {});
    await rm(dir, { recursive: true, force: true });
  }
});
