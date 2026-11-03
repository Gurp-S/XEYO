import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, rm, stat, utimes, writeFile, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { build, parseArgs } from '../../lib/build.js';
import { parseConcurrency } from '../../lib/pool.js';
import { watchBuild } from '../../lib/watch.js';

const ROOT = path.resolve(import.meta.dirname, '..', '..');

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-regress-'));
  await cp(path.join(ROOT, 'src'), path.join(dir, 'src'), { recursive: true });
  return dir;
}

function opts(overrides = {}) {
  return {
    src: 'src',
    out: 'out',
    manifest: 'build-manifest.json',
    dryRun: false,
    json: false,
    watch: false,
    concurrency: 4,
    help: false,
    ...overrides,
  };
}

async function run(dir, overrides) {
  return build(opts(overrides), dir);
}

async function manifestOf(dir) {
  return JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
}

async function outText(dir, rel) {
  return readFile(path.join(dir, 'out', rel), 'utf8');
}

async function exists(file) {
  try {
    await access(file);
    return true;
  } catch {
    return false;
  }
}

test('changing an asset referenced by url() rebuilds the stylesheet', async () => {
  const dir = await project();
  try {
    const first = await run(dir);
    assert.ok(first.built.includes('style.css'));
    const original = await outText(dir, 'style.css');
    const originalName = /url\(([^)]+)\)/.exec(original)[1];
    assert.match(originalName, /^img\.[0-9a-f]{8}\.png$/);
    assert.ok(await exists(path.join(dir, 'out', originalName)));

    await writeFile(path.join(dir, 'src', 'img.png'), Buffer.from('different bytes'));
    const second = await run(dir);
    assert.deepEqual(second.built.sort(), ['img.png', 'style.css']);

    const rewritten = await outText(dir, 'style.css');
    const newName = /url\(([^)]+)\)/.exec(rewritten)[1];
    assert.notEqual(newName, originalName);
    assert.ok(await exists(path.join(dir, 'out', newName)));
    assert.equal(await exists(path.join(dir, 'out', originalName)), false);

    const third = await run(dir);
    assert.deepEqual(third.built, []);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('changing a base file pulled in through extends rebuilds the derived file', async () => {
  const dir = await project();
  try {
    await run(dir);
    await writeFile(path.join(dir, 'src', 'base.json'), '{"name":"base","level":2}\n');
    const second = await run(dir);
    assert.deepEqual(second.built.sort(), ['base.json', 'data.json']);
    const merged = JSON.parse(await outText(dir, 'data.json'));
    assert.deepEqual(merged, { name: 'demo', level: 2 });
    assert.equal('extends' in merged, false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('rewriting a source without changing its mtime still rebuilds', async () => {
  const dir = await project();
  try {
    await run(dir);
    const target = path.join(dir, 'src', 'b.js');
    const before = await stat(target);
    await writeFile(target, "export const b = 'B2';\n");
    await utimes(target, before.atimeMs / 1000, before.mtimeMs / 1000);
    const after = await stat(target);
    assert.ok(Math.abs(after.mtimeMs - before.mtimeMs) < 1);

    const second = await run(dir);
    assert.deepEqual(second.built.sort(), ['a.js', 'b.js']);
    assert.match(await outText(dir, 'b.js'), /B2/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('deleting a source removes its output and its manifest entry', async () => {
  const dir = await project();
  try {
    await run(dir);
    await rm(path.join(dir, 'src', 'extra.js'));
    const second = await run(dir);
    assert.deepEqual(second.removed, ['extra.js']);
    assert.equal(await exists(path.join(dir, 'out', 'extra.js')), false);
    assert.equal('extra.js' in (await manifestOf(dir)).files, false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a manifest naming outputs that no longer exist heals', async () => {
  const dir = await project();
  try {
    await run(dir);
    const manifestPath = path.join(dir, 'build-manifest.json');
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
    manifest.files['ghost.js'] = { key: 'x', deps: {}, out: ['ghost.js'] };
    manifest.files['a.js'].out = ['a.js', 'nope.js'];
    await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

    const second = await run(dir);
    assert.deepEqual(second.built, ['a.js']);
    const healed = await manifestOf(dir);
    assert.equal('ghost.js' in healed.files, false);
    assert.deepEqual(healed.files['a.js'].out, ['a.js']);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a half-written manifest does not crash the next build', async () => {
  const dir = await project();
  try {
    await writeFile(path.join(dir, 'build-manifest.json'), '{"version":2,"files":{"a.js":{"key":"x"');
    const report = await run(dir);
    assert.equal(report.built.length, 7);
    assert.equal((await manifestOf(dir)).version, 2);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--concurrency bounds parallelism and does not change output', async () => {
  const serial = await project();
  const parallel = await project();
  try {
    await run(serial, { concurrency: 1 });
    await run(parallel, { concurrency: 8 });
    for (const rel of ['a.js', 'b.js', 'base.json', 'data.json', 'extra.js', 'img.png', 'style.css']) {
      const a = await readFile(path.join(serial, 'out', rel));
      const b = await readFile(path.join(parallel, 'out', rel));
      assert.deepEqual(a, b, rel);
    }
    assert.deepEqual(await manifestOf(serial), await manifestOf(parallel));
    assert.throws(() => parseConcurrency('0'), /positive integer/);
    assert.throws(() => parseConcurrency('two'), /positive integer/);
    assert.equal(parseArgs(['--concurrency', '3']).concurrency, 3);
    assert.equal(parseArgs([]).concurrency, 4);
  } finally {
    await rm(serial, { recursive: true, force: true });
    await rm(parallel, { recursive: true, force: true });
  }
});

test('--dry-run writes nothing', async () => {
  const dir = await project();
  try {
    const report = await run(dir, { dryRun: true });
    assert.equal(report.dryRun, true);
    assert.equal(report.built.length, 7);
    assert.equal(await exists(path.join(dir, 'out')), false);
    assert.equal(await exists(path.join(dir, 'build-manifest.json')), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('watch rebuilds on change and stops on abort', async () => {
  const dir = await project();
  const controller = new AbortController();
  try {
    const reports = [];
    let notify;
    const nextReport = () => new Promise((resolve) => {
      notify = resolve;
    });
    let pending = nextReport();
    const finished = watchBuild(opts(), {
      cwd: dir,
      signal: controller.signal,
      onChange: (report, error) => {
        reports.push(error ? { error } : report);
        notify();
      },
    });

    await pending;
    assert.equal(reports[0].built.length, 7);
    pending = nextReport();
    await writeFile(path.join(dir, 'src', 'b.js'), "export const b = 'B3';\n");
    await pending;
    assert.deepEqual(reports[1].built.sort(), ['a.js', 'b.js']);
    assert.match(await outText(dir, 'b.js'), /B3/);

    controller.abort();
    await finished;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
