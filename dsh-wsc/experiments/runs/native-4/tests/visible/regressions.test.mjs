import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir, rm, stat, unlink, utimes, writeFile } from 'node:fs/promises';
import path from 'node:path';

import { build, cleanup, cli, delay, exists, outFiles, project, readManifest, treeBytes, waitFor } from './helpers.mjs';
import { build as runBuild, parseArgs } from '../../lib/build.js';
import { watchBuild } from '../../lib/watch.js';

const HASHED_ASSET = /url\((img\.[0-9a-f]{8}\.png)\)/;

test('a rewrite that keeps size and mtime still rebuilds the file', async () => {
  const dir = await project();
  try {
    await build(dir);
    const source = path.join(dir, 'src/b.js');
    const before = await readFile(source);
    const { atime, mtime } = await stat(source);
    const rewritten = Buffer.from(before.toString('utf8').replace("'B1'", "'B2'"));
    assert.equal(rewritten.length, before.length, 'the fixture rewrite must keep the byte size');
    await writeFile(source, rewritten);
    await utimes(source, atime, mtime);

    const report = await build(dir);
    assert.ok(report.built.includes('b.js'), 'content change must invalidate the entry');
    assert.match(await readFile(path.join(dir, 'out/b.js'), 'utf8'), /'B2'/);
  } finally {
    await cleanup(dir);
  }
});

test('changing a url() asset rebuilds the stylesheet and drops the old hashed asset', async () => {
  const dir = await project();
  try {
    await build(dir);
    const before = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const oldName = before.match(HASHED_ASSET)?.[1];
    assert.ok(oldName, 'the stylesheet must reference a hashed asset');
    assert.ok(await exists(path.join(dir, 'out', oldName)));

    await writeFile(path.join(dir, 'src/img.png'), Buffer.from('a different image payload'));
    const report = await build(dir);
    assert.ok(report.built.includes('style.css'), 'the stylesheet depends on the asset');
    assert.ok(report.built.includes('img.png'));

    const after = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const newName = after.match(HASHED_ASSET)?.[1];
    assert.ok(newName && newName !== oldName, 'the reference must move to the new fingerprint');
    assert.ok(await exists(path.join(dir, 'out', newName)));
    assert.equal(await exists(path.join(dir, 'out', oldName)), false, 'the stale asset must be pruned');
  } finally {
    await cleanup(dir);
  }
});

test('changing a JSON extends base rebuilds the derived file', async () => {
  const dir = await project();
  try {
    await build(dir);
    assert.equal(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')).level, 1);

    await writeFile(path.join(dir, 'src/base.json'), '{"name":"base","level":2}\n');
    const report = await build(dir);
    assert.ok(report.built.includes('data.json'), 'the derived file depends on its base');

    const merged = JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8'));
    assert.equal(merged.level, 2);
    assert.equal(merged.name, 'demo');
  } finally {
    await cleanup(dir);
  }
});

test('deleting a source removes its output and its manifest entry', async () => {
  const dir = await project();
  try {
    await build(dir);
    assert.ok(await exists(path.join(dir, 'out/extra.js')));
    assert.ok((await readManifest(dir)).files['extra.js']);

    await unlink(path.join(dir, 'src/extra.js'));
    const report = await build(dir);
    assert.ok(report.removed.includes('extra.js'));
    assert.equal(await exists(path.join(dir, 'out/extra.js')), false);
    assert.equal((await readManifest(dir)).files['extra.js'], undefined);
  } finally {
    await cleanup(dir);
  }
});

test('a manifest entry whose output vanished is rebuilt', async () => {
  const dir = await project();
  try {
    await build(dir);
    await rm(path.join(dir, 'out/a.js'));

    const report = await build(dir);
    assert.ok(report.built.includes('a.js'), 'a missing output must heal');
    assert.ok(await exists(path.join(dir, 'out/a.js')));
  } finally {
    await cleanup(dir);
  }
});

test('a truncated manifest does not crash the next build and leaves no temp file', async () => {
  const dir = await project();
  try {
    await build(dir);
    await writeFile(path.join(dir, 'build-manifest.json'), '{"version": 2, "files": {');

    const report = await build(dir);
    assert.equal(report.built.length, 7, 'every source is rebuilt after losing the manifest');
    assert.equal((await readManifest(dir)).version, 2);
    assert.deepEqual((await readdir(dir)).filter((name) => name.endsWith('.tmp')), []);
  } finally {
    await cleanup(dir);
  }
});

test('--dry-run writes nothing at all', async () => {
  const dir = await project();
  try {
    const fresh = await cli(dir, ['--json', '--dry-run']);
    assert.equal(fresh.code, 0);
    assert.equal(JSON.parse(fresh.stdout).dryRun, true);
    assert.equal(await exists(path.join(dir, 'out')), false);
    assert.equal(await exists(path.join(dir, 'build-manifest.json')), false);

    await build(dir);
    await writeFile(path.join(dir, 'src/b.js'), "export const b = 'B9';\n");
    const before = await readFile(path.join(dir, 'out/b.js'));
    const manifestBefore = await readFile(path.join(dir, 'build-manifest.json'));
    const planned = JSON.parse((await cli(dir, ['--json', '--dry-run'])).stdout);
    assert.ok(planned.built.includes('b.js'));
    assert.deepEqual(await readFile(path.join(dir, 'out/b.js')), before);
    assert.deepEqual(await readFile(path.join(dir, 'build-manifest.json')), manifestBefore);
  } finally {
    await cleanup(dir);
  }
});

test('--concurrency bounds the work without changing the result', async () => {
  const serialDir = await project();
  const parallelDir = await project();
  try {
    await build(serialDir);
    const parallel = await build(parallelDir, ['--concurrency', '4']);

    assert.deepEqual(parallel.built, ['a.js', 'b.js', 'base.json', 'data.json', 'extra.js', 'img.png', 'style.css']);
    assert.deepEqual(await outFiles(parallelDir), await outFiles(serialDir));

    const serial = await treeBytes(path.join(serialDir, 'out'));
    const wide = await treeBytes(path.join(parallelDir, 'out'));
    for (const [rel, bytes] of serial) assert.deepEqual(wide.get(rel), bytes, `${rel} must match`);

    assert.equal(
      await readFile(path.join(parallelDir, 'build-manifest.json'), 'utf8'),
      await readFile(path.join(serialDir, 'build-manifest.json'), 'utf8'),
    );

    const again = await build(parallelDir, ['--concurrency', '4']);
    assert.deepEqual(again.built, [], 'a concurrent rebuild is still incremental');
  } finally {
    await cleanup(serialDir);
    await cleanup(parallelDir);
  }
});

test('--watch rebuilds when a source changes', async () => {
  const dir = await project();
  const controller = new AbortController();
  const reports = [];
  const errors = [];
  try {
    const done = watchBuild(parseArgs(['--json']), {
      cwd: dir,
      intervalMs: 20,
      build: runBuild,
      onReport: (report) => reports.push(report),
      onError: (error) => errors.push(error),
      signal: controller.signal,
    });

    await waitFor(() => reports.length === 1);
    assert.ok(reports[0].built.includes('a.js'));
    await delay(200);

    await writeFile(path.join(dir, 'src/b.js'), "export const b = 'W1';\n");
    await waitFor(() => reports.length >= 2);
    assert.ok(reports.some((report) => report.built.includes('b.js')), 'the change must trigger a rebuild');
    assert.deepEqual(errors, []);

    controller.abort();
    await done;
    assert.match(await readFile(path.join(dir, 'out/b.js'), 'utf8'), /'W1'/);
  } finally {
    controller.abort();
    await cleanup(dir);
  }
});

test('invalid options exit non-zero', async () => {
  const dir = await project();
  try {
    const bad = await cli(dir, ['--concurrency', '0']);
    assert.equal(bad.code, 1);
    assert.match(bad.stderr, /--concurrency needs a positive integer/);

    const conflicting = await cli(dir, ['--watch', '--dry-run']);
    assert.equal(conflicting.code, 1);
    assert.match(conflicting.stderr, /--watch cannot be combined with --dry-run/);
    assert.equal(await exists(path.join(dir, 'out')), false);
  } finally {
    await cleanup(dir);
  }
});
