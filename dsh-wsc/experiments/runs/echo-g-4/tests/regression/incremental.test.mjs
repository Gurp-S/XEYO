import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, stat, unlink, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { build } from '../../lib/build.js';

const OPTS = { src: 'src', out: 'out', manifest: 'build-manifest.json', concurrency: 4 };

async function project(files) {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-regress-'));
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, 'src', rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  return dir;
}

const buildIn = (dir) => build(OPTS, dir);

const PNG_A = Buffer.from([0x89, 0x50, 0x4e, 0x47, 1, 1, 1, 1]);
const PNG_B = Buffer.from([0x89, 0x50, 0x4e, 0x47, 2, 2, 2, 2]);

test('rewriting a file with the same size and mtime still rebuilds it', async () => {
  const dir = await project({ 'a.js': 'const x = 1;\n' });
  try {
    await buildIn(dir);
    const abs = path.join(dir, 'src/a.js');
    const before = await stat(abs);
    await writeFile(abs, 'const x = 2;\n');
    await utimes(abs, before.atime, before.mtime);

    const report = await buildIn(dir);
    assert.deepEqual(report.built, ['a.js']);
    assert.match(await readFile(path.join(dir, 'out/a.js'), 'utf8'), /^const x = 2;/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a stylesheet rebuilds when a url() asset changes, and drops the stale asset', async () => {
  const dir = await project({ 'style.css': 'body{background:url(img.png)}\n', 'img.png': PNG_A });
  try {
    await buildIn(dir);
    const first = JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
    assert.equal(Object.keys(first.files['style.css'].deps).join(','), 'img.png');

    await writeFile(path.join(dir, 'src/img.png'), PNG_B);
    const report = await buildIn(dir);

    assert.ok(report.built.includes('style.css'));
    assert.equal(report.deleted.length, 1);
    assert.match(report.deleted[0], /^img\.[0-9a-f]{8}\.png$/);
    assert.ok(!(await readFile(path.join(dir, 'out/style.css'), 'utf8')).includes(report.deleted[0]));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a json document rebuilds when its extends base changes', async () => {
  const dir = await project({ 'base.json': '{"b":2}\n', 'data.json': '{"extends":"./base.json","a":1}\n' });
  try {
    await buildIn(dir);
    assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')), { b: 2, a: 1 });

    await writeFile(path.join(dir, 'src/base.json'), '{"b":3}\n');
    const report = await buildIn(dir);

    // `data.json` itself is byte-identical, so its rebuild can only come from
    // the changed `extends` base.
    assert.deepEqual(report.built, ['base.json', 'data.json']);
    assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')), { b: 3, a: 1 });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('deleting a source removes its outputs and its manifest entry', async () => {
  const dir = await project({ 'a.js': 'export const a = 1;\n', 'extra.js': 'export const e = 1;\n' });
  try {
    await buildIn(dir);
    await unlink(path.join(dir, 'src/extra.js'));
    const report = await buildIn(dir);

    assert.deepEqual(report.removed, ['extra.js']);
    assert.deepEqual(report.deleted, ['extra.js']);
    await assert.rejects(stat(path.join(dir, 'out/extra.js')));
    const manifest = JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
    assert.equal(manifest.files['extra.js'], undefined);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a truncated manifest degrades to a full rebuild instead of failing', async () => {
  const dir = await project({ 'a.js': 'export const a = 1;\n', 'b.js': 'export const b = 1;\n' });
  try {
    await writeFile(path.join(dir, 'build-manifest.json'), '{"version":2}\n');
    const report = await buildIn(dir);
    assert.deepEqual(report.built, ['a.js', 'b.js']);
    assert.equal(report.manifest, 'corrupt');
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('an unchanged tree skips every file', async () => {
  const dir = await project({ 'a.js': 'export const a = 1;\n', 'style.css': 'a{color:red}\n' });
  try {
    await buildIn(dir);
    const report = await buildIn(dir);
    assert.deepEqual(report.built, []);
    assert.deepEqual(report.skipped, ['a.js', 'style.css']);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
