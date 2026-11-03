import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repoRoot = path.dirname(path.dirname(path.dirname(fileURLToPath(import.meta.url))));

function load(rel) {
  return import(pathToFileURL(path.join(repoRoot, rel)).href);
}

const { build, parseArgs } = await load('lib/build.js');
const { startWatch } = await load('lib/watch.js');
const { mapLimit } = await load('lib/concurrency.js');

const OPTIONS = parseArgs([]);

async function project(files) {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'mini-build-contract-'));
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  return dir;
}

async function exists(abs) {
  try {
    await stat(abs);
    return true;
  } catch {
    return false;
  }
}

async function snapshot(dir) {
  const files = {};
  async function visit(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const abs = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(abs);
      else files[path.relative(dir, abs).split(path.sep).join('/')] = (await readFile(abs)).toString('base64');
    }
  }
  await visit(dir);
  return files;
}

async function waitFor(predicate, timeoutMs = 8000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await predicate()) return true;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  return false;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test('a changed asset rebuilds the stylesheet that references it', async (t) => {
  const dir = await project({
    'src/style.css': '.card { background: url(img.png); }\n',
    'src/img.png': Buffer.from('first-image-bytes'),
  });
  t.after(() => rm(dir, { recursive: true, force: true }));

  await build(OPTIONS, dir);
  const first = (await readFile(path.join(dir, 'out/style.css'), 'utf8')).match(/url\(img\.([0-9a-f]{8})\.png\)/);
  assert.ok(first, 'stylesheet was rewritten');
  assert.ok(await exists(path.join(dir, 'out', `img.${first[1]}.png`)), 'asset emitted next to the stylesheet');

  await writeFile(path.join(dir, 'src/img.png'), 'second-image-bytes');
  const report = await build(OPTIONS, dir);

  assert.ok(report.built.includes('style.css'), 'stylesheet rebuilt after its asset changed');
  const second = (await readFile(path.join(dir, 'out/style.css'), 'utf8')).match(/url\(img\.([0-9a-f]{8})\.png\)/);
  assert.ok(second, 'stylesheet still references an asset');
  assert.notEqual(second[1], first[1], 'reference points at the new asset name');
  assert.ok(await exists(path.join(dir, 'out', `img.${second[1]}.png`)), 'new asset written');
  assert.ok(!(await exists(path.join(dir, 'out', `img.${first[1]}.png`))), 'old asset removed');
});

test('a changed base rebuilds the json file that extends it', async (t) => {
  const dir = await project({
    'src/data.json': JSON.stringify({ extends: './base.json', name: 'demo' }),
    'src/base.json': JSON.stringify({ name: 'base', level: 1 }),
  });
  t.after(() => rm(dir, { recursive: true, force: true }));

  await build(OPTIONS, dir);
  assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')), { name: 'demo', level: 1 });

  await writeFile(path.join(dir, 'src/base.json'), JSON.stringify({ name: 'base', level: 2 }));
  const report = await build(OPTIONS, dir);

  assert.ok(report.built.includes('data.json'), 'derived file rebuilt after its base changed');
  assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')), { name: 'demo', level: 2 });
});

test('rewriting a source without changing mtime rebuilds it', async (t) => {
  const dir = await project({ 'src/a.js': 'export const a = 1;\n' });
  t.after(() => rm(dir, { recursive: true, force: true }));

  await build(OPTIONS, dir);
  const before = await readFile(path.join(dir, 'out/a.js'), 'utf8');

  const source = path.join(dir, 'src/a.js');
  const original = await stat(source);
  await writeFile(source, 'export const a = 2;\n');
  await utimes(source, original.atime, original.mtime);

  const report = await build(OPTIONS, dir);
  assert.ok(report.built.includes('a.js'), 'content change detected despite identical size and mtime');
  assert.notEqual(await readFile(path.join(dir, 'out/a.js'), 'utf8'), before);
});

test('deleting a source removes its outputs and manifest entry', async (t) => {
  const dir = await project({
    'src/a.js': "import { b } from './b.js';\nexport const a = b;\n",
    'src/b.js': "export const b = 'B';\n",
    'src/lib/c.js': 'export const c = 1;\n',
  });
  t.after(() => rm(dir, { recursive: true, force: true }));

  await build(OPTIONS, dir);
  assert.ok(await exists(path.join(dir, 'out/b.js')));
  assert.ok(await exists(path.join(dir, 'out/lib/c.js')));

  await rm(path.join(dir, 'src/b.js'));
  await rm(path.join(dir, 'src/lib/c.js'));
  const report = await build(OPTIONS, dir);

  assert.deepEqual(report.removed, ['b.js', 'lib/c.js']);
  assert.ok(!(await exists(path.join(dir, 'out/b.js'))), 'output of the deleted source removed');
  assert.ok(!(await exists(path.join(dir, 'out/lib/c.js'))), 'nested output removed');
  assert.ok(!(await exists(path.join(dir, 'out/lib'))), 'emptied output directory pruned');

  const manifest = JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
  assert.equal(manifest.files['b.js'], undefined);
  assert.equal(manifest.files['lib/c.js'], undefined);
  assert.ok(manifest.files['a.js'], 'remaining source still tracked');
});

test('a missing output is rebuilt', async (t) => {
  const dir = await project({ 'src/a.js': 'export const a = 1;\n' });
  t.after(() => rm(dir, { recursive: true, force: true }));

  await build(OPTIONS, dir);
  await rm(path.join(dir, 'out/a.js'));

  const healed = await build(OPTIONS, dir);
  assert.ok(healed.built.includes('a.js'), 'manifest entry alone does not count as built');
  assert.ok(await exists(path.join(dir, 'out/a.js')));

  const settled = await build(OPTIONS, dir);
  assert.deepEqual(settled.built, []);
});

test('a truncated manifest does not break the next build', async (t) => {
  const dir = await project({
    'src/a.js': 'export const a = 1;\n',
    'src/b.js': 'export const b = 2;\n',
  });
  t.after(() => rm(dir, { recursive: true, force: true }));

  await build(OPTIONS, dir);
  await writeFile(path.join(dir, 'build-manifest.json'), '{"version": 2, "files": {"a.js": {"key"');

  const report = await build(OPTIONS, dir);
  assert.deepEqual(report.built, ['a.js', 'b.js'], 'unreadable manifest degrades to a full build');
  assert.ok(await exists(path.join(dir, 'out/a.js')));
  assert.equal(JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8')).version, 2);
});

test('--concurrency bounds simultaneous work and keeps output stable', async (t) => {
  assert.equal(parseArgs(['--concurrency', '4']).concurrency, 4);
  assert.throws(() => parseArgs(['--concurrency', '0']), /positive integer/);
  assert.throws(() => parseArgs(['--concurrency', '1.5']), /positive integer/);
  assert.throws(() => parseArgs(['--concurrency']), /needs a value/);

  let active = 0;
  let peak = 0;
  await mapLimit([...Array(12).keys()], 3, async () => {
    active += 1;
    peak = Math.max(peak, active);
    await sleep(10);
    active -= 1;
  });
  assert.ok(peak <= 3, `at most 3 tasks at a time, saw ${peak}`);
  assert.ok(peak > 1, 'tasks do run in parallel');

  const sources = {
    'src/a.js': "import { b } from './b.js';\nexport const a = b;\n",
    'src/b.js': "export const b = 'B1';\n",
    'src/style.css': '.card { background: url(img.png); }\n',
    'src/img.png': Buffer.from('png-bytes'),
  };
  const serial = await project(sources);
  const parallel = await project(sources);
  t.after(() => rm(serial, { recursive: true, force: true }));
  t.after(() => rm(parallel, { recursive: true, force: true }));

  await build(OPTIONS, serial);
  await build(parseArgs(['--concurrency', '4']), parallel);
  assert.deepEqual(await snapshot(path.join(parallel, 'out')), await snapshot(path.join(serial, 'out')));
});

test('--dry-run writes nothing', async (t) => {
  const dir = await project({ 'src/a.js': 'export const a = 1;\n' });
  t.after(() => rm(dir, { recursive: true, force: true }));

  const plan = await build(parseArgs(['--dry-run']), dir);
  assert.deepEqual(plan.built, ['a.js']);
  assert.equal(await exists(path.join(dir, 'out')), false, 'no output directory');
  assert.equal(await exists(path.join(dir, 'build-manifest.json')), false, 'no manifest');

  await build(OPTIONS, dir);
  const built = await readFile(path.join(dir, 'out/a.js'), 'utf8');
  await writeFile(path.join(dir, 'src/a.js'), 'export const a = 2;\n');

  const second = await build(parseArgs(['--dry-run']), dir);
  assert.deepEqual(second.built, ['a.js']);
  assert.equal(await readFile(path.join(dir, 'out/a.js'), 'utf8'), built, 'existing output untouched');
});

test('--watch rebuilds after a source change', async (t) => {
  const dir = await project({ 'src/a.js': 'export const a = 1;\n' });
  const reports = [];
  const errors = [];
  const watcher = await startWatch(
    OPTIONS,
    { onReport: (report) => reports.push(report), onError: (error) => errors.push(error) },
    dir,
  );
  t.after(async () => {
    watcher.close();
    await rm(dir, { recursive: true, force: true });
  });

  assert.equal(reports.length, 1, 'one report for the initial build');
  assert.deepEqual(reports[0].built, ['a.js']);
  const before = await readFile(path.join(dir, 'out/a.js'), 'utf8');

  await writeFile(path.join(dir, 'src/a.js'), 'export const a = 2;\n');
  assert.ok(await waitFor(() => reports.length >= 2), 'watcher produced a second report');
  assert.ok(reports[1].built.includes('a.js'));
  assert.notEqual(await readFile(path.join(dir, 'out/a.js'), 'utf8'), before);

  await mkdir(path.join(dir, 'src/nested'));
  await writeFile(path.join(dir, 'src/nested/d.js'), 'export const d = 1;\n');
  await sleep(200);
  await writeFile(path.join(dir, 'src/a.js'), 'export const a = 3;\n');
  assert.ok(
    await waitFor(() => reports.some((report) => report.built.includes('nested/d.js'))),
    'source directory added after startup is watched',
  );
  assert.deepEqual(errors, []);
});

test('a full build and an incremental build produce identical output', async (t) => {
  const sources = {
    'src/a.js': "import { b } from './b.js';\nexport const a = b;\n",
    'src/b.js': "export const b = 'B1';\n",
    'src/style.css': '.card { background: url(img.png); }\n',
    'src/data.json': JSON.stringify({ extends: './base.json', name: 'demo' }),
    'src/base.json': JSON.stringify({ name: 'base', level: 1 }),
    'src/img.png': Buffer.from('png-bytes'),
  };
  const fresh = await project(sources);
  const churned = await project(sources);
  t.after(() => rm(fresh, { recursive: true, force: true }));
  t.after(() => rm(churned, { recursive: true, force: true }));

  await build(OPTIONS, fresh);
  const expected = await snapshot(path.join(fresh, 'out'));

  await build(OPTIONS, churned);
  await writeFile(path.join(churned, 'src/b.js'), "export const b = 'B2';\n");
  await writeFile(path.join(churned, 'src/base.json'), JSON.stringify({ name: 'base', level: 2 }));
  await writeFile(path.join(churned, 'src/img.png'), Buffer.from('other-png-bytes'));
  await build(OPTIONS, churned);

  for (const [rel, content] of Object.entries(sources)) {
    await writeFile(path.join(churned, rel), content);
  }
  await build(OPTIONS, churned);

  assert.deepEqual(await snapshot(path.join(churned, 'out')), expected);
});
