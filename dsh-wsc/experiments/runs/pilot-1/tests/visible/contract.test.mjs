import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  stat,
  unlink,
  utimes,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { build, parseArgs } from '../../lib/build.js';
import { mapLimit } from '../../lib/limit.js';
import { startWatch } from '../../lib/watch.js';

const FIXTURE = {
  'src/a.js': "import { b } from './b.js';\nexport const a = 'AAA';\nexport const b = b;\n",
  'src/b.js': "export const b = 'B1';\n",
  'src/extra.js': 'export const extra = true;\n',
  'src/style.css': ".card {\n  background: url( 'img.png' );\n}\n",
  'src/img.png': Buffer.from('PNG-ONE'),
  'src/base.json': '{\n  "name": "base",\n  "level": 1\n}\n',
  'src/data.json': '{\n  "extends": "./base.json",\n  "name": "demo"\n}\n',
};

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-contract-'));
  for (const [rel, content] of Object.entries(FIXTURE)) {
    const abs = path.join(dir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  return dir;
}

function options(overrides = {}) {
  return { ...parseArgs([]), ...overrides };
}

async function run(dir, overrides = {}) {
  return build(options(overrides), dir);
}

async function manifest(dir) {
  return JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
}

async function exists(file) {
  try {
    return (await stat(file)).isFile();
  } catch {
    return false;
  }
}

async function pathExists(target) {
  try {
    await stat(target);
    return true;
  } catch {
    return false;
  }
}

async function snapshot(dir) {
  const files = {};
  const visit = async (current) => {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const abs = path.join(current, entry.name);
      if (entry.isDirectory()) await visit(abs);
      else if (entry.isFile()) {
        files[path.relative(dir, abs).split(path.sep).join('/')] =
          (await readFile(abs)).toString('base64');
      }
    }
  };
  await visit(dir);
  return files;
}

async function waitFor(predicate, timeout = 10000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error('timed out waiting for condition');
}

async function waitForReport(reports, predicate, from = 0) {
  await waitFor(() => reports.slice(from).some(predicate));
  return reports.slice(from).find(predicate);
}

test('a css url() target is a dependency and stale hashed assets are removed', async () => {
  const dir = await project();
  try {
    await run(dir);
    const first = await manifest(dir);
    assert.equal(first.files['style.css'].deps['img.png'], first.files['img.png'].key);

    const firstCss = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const oldName = firstCss.match(/url\((img\.[0-9a-f]{8}\.png)\)/)[1];
    assert.ok(await exists(path.join(dir, 'out', oldName)));

    await writeFile(path.join(dir, 'src/img.png'), Buffer.from('PNG-TWO'));
    const second = await run(dir);
    assert.ok(second.built.includes('style.css'));

    const secondCss = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const newName = secondCss.match(/url\((img\.[0-9a-f]{8}\.png)\)/)[1];
    assert.notEqual(newName, oldName);
    assert.ok(await exists(path.join(dir, 'out', newName)));
    assert.equal(await exists(path.join(dir, 'out', oldName)), false);

    const next = await manifest(dir);
    assert.ok(next.files['style.css'].out.includes(newName));
    assert.equal(next.files['style.css'].out.includes(oldName), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a nested stylesheet emits its hashed asset next to itself', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-contract-'));
  try {
    await mkdir(path.join(dir, 'src/css'), { recursive: true });
    await writeFile(path.join(dir, 'src/css/style.css'), '.x { background: url(../img.png); }\n');
    await writeFile(path.join(dir, 'src/img.png'), Buffer.from('PNG-NESTED'));

    await run(dir);
    const css = await readFile(path.join(dir, 'out/css/style.css'), 'utf8');
    const name = css.match(/url\((img\.[0-9a-f]{8}\.png)\)/)[1];
    assert.equal(await exists(path.join(dir, 'out/css', name)), true);
    assert.equal(await exists(path.join(dir, 'out', name)), false);

    await writeFile(path.join(dir, 'src/img.png'), Buffer.from('PNG-NESTED-2'));
    await run(dir);
    const nextCss = await readFile(path.join(dir, 'out/css/style.css'), 'utf8');
    const nextName = nextCss.match(/url\((img\.[0-9a-f]{8}\.png)\)/)[1];
    assert.notEqual(nextName, name);
    assert.equal(await exists(path.join(dir, 'out/css', name)), false);
    assert.equal(await exists(path.join(dir, 'out/css', nextName)), true);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a json extends base is a dependency of the derived file', async () => {
  const dir = await project();
  try {
    await run(dir);
    const first = await manifest(dir);
    assert.equal(first.files['data.json'].deps['base.json'], first.files['base.json'].key);

    await writeFile(
      path.join(dir, 'src/base.json'),
      '{\n  "name": "base",\n  "level": 2\n}\n',
    );
    const second = await run(dir);
    assert.ok(second.built.includes('data.json'));

    const output = JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8'));
    assert.deepEqual(output, { name: 'demo', level: 2 });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a content rewrite with an unchanged mtime still invalidates the output', async () => {
  const dir = await project();
  try {
    await run(dir);
    const file = path.join(dir, 'src/b.js');
    const before = await stat(file);
    await writeFile(file, "export const b = 'B2';\n");
    await utimes(file, before.atime, before.mtime);

    const second = await run(dir);
    assert.ok(second.built.includes('b.js'));
    assert.match(await readFile(path.join(dir, 'out/b.js'), 'utf8'), /B2/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('deleting a source removes its output and manifest entry, and missing outputs heal', async () => {
  const dir = await project();
  try {
    await run(dir);
    await unlink(path.join(dir, 'src/extra.js'));
    const second = await run(dir);
    assert.ok(second.removed.includes('extra.js'));
    assert.equal(await exists(path.join(dir, 'out/extra.js')), false);
    assert.equal('extra.js' in (await manifest(dir)).files, false);

    // A manifest entry is not proof that the output is still on disk.
    await unlink(path.join(dir, 'out/a.js'));
    const third = await run(dir);
    assert.ok(third.built.includes('a.js'));
    assert.ok(await exists(path.join(dir, 'out/a.js')));

    // The hashed asset named by a stylesheet is also an output of that entry.
    const css = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const hashed = css.match(/url\((img\.[0-9a-f]{8}\.png)\)/)[1];
    await unlink(path.join(dir, 'out', hashed));
    const fourth = await run(dir);
    assert.ok(fourth.built.includes('style.css'));
    assert.ok(await exists(path.join(dir, 'out', hashed)));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('deleting a referenced dependency cleans up and heals when it returns', async () => {
  const dir = await project();
  try {
    await run(dir);
    const css = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const hashed = css.match(/url\((img\.[0-9a-f]{8}\.png)\)/)[1];

    await unlink(path.join(dir, 'src/img.png'));
    const second = await run(dir);
    assert.ok(second.built.includes('style.css'));
    assert.equal(await exists(path.join(dir, 'out', hashed)), false);
    assert.match(await readFile(path.join(dir, 'out/style.css'), 'utf8'), /url\(img\.png\)/);

    await unlink(path.join(dir, 'src/base.json'));
    const third = await run(dir);
    assert.ok(third.built.includes('data.json'));
    assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')), {
      name: 'demo',
    });

    await writeFile(path.join(dir, 'src/img.png'), Buffer.from('PNG-ONE'));
    const fourth = await run(dir);
    assert.ok(fourth.built.includes('style.css'));
    assert.match(
      await readFile(path.join(dir, 'out/style.css'), 'utf8'),
      /url\(img\.[0-9a-f]{8}\.png\)/,
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a source changing between file and directory does not collide with old outputs', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-contract-'));
  try {
    await mkdir(path.join(dir, 'src'), { recursive: true });
    await writeFile(path.join(dir, 'src/foo'), 'file\n');
    await run(dir);
    assert.ok(await exists(path.join(dir, 'out/foo')));

    await unlink(path.join(dir, 'src/foo'));
    await mkdir(path.join(dir, 'src/foo'), { recursive: true });
    await writeFile(path.join(dir, 'src/foo/bar.js'), 'export const x = 1;\n');
    const second = await run(dir);
    assert.ok(second.removed.includes('foo'));
    assert.ok(await exists(path.join(dir, 'out/foo/bar.js')));

    await rm(path.join(dir, 'src/foo'), { recursive: true, force: true });
    await writeFile(path.join(dir, 'src/foo'), 'file again\n');
    const third = await run(dir);
    assert.ok(third.removed.includes('foo/bar.js'));
    assert.ok(await exists(path.join(dir, 'out/foo')));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('outputs and the manifest are not sources when they live under --src', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-contract-'));
  const overrides = { out: 'src/out', manifest: 'src/build-manifest.json' };
  try {
    await mkdir(path.join(dir, 'src'), { recursive: true });
    await writeFile(path.join(dir, 'src/a.js'), 'export const a = 1;\n');
    await run(dir, overrides);
    const second = await run(dir, overrides);
    assert.equal(second.built.length, 0);
    assert.ok(await exists(path.join(dir, 'src/out/a.js')));
    assert.equal(await exists(path.join(dir, 'src/out/out/a.js')), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('an output directory above --src does not hide sources', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-contract-'));
  const overrides = { out: '.', manifest: 'build-manifest.json' };
  try {
    await mkdir(path.join(dir, 'src'), { recursive: true });
    await writeFile(path.join(dir, 'src/a.js'), 'export const a = 1;\n');
    const first = await run(dir, overrides);
    assert.ok(first.built.includes('a.js'));
    assert.ok(await exists(path.join(dir, 'a.js')));
    const second = await run(dir, overrides);
    assert.equal(second.built.length, 0);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a truncated or malformed manifest is discarded instead of crashing the build', async () => {
  const dir = await project();
  try {
    await run(dir);
    const manifestPath = path.join(dir, 'build-manifest.json');

    await writeFile(manifestPath, '{"version": 2, "files": {"a.js": ');
    const second = await run(dir);
    assert.ok(second.built.includes('a.js'));
    assert.ok((await manifest(dir)).files['a.js']);

    await writeFile(manifestPath, '{"version": 2}\n');
    const third = await run(dir);
    assert.ok(third.built.includes('a.js'));
    assert.ok((await manifest(dir)).files['style.css']);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('dry-run reports the plan without writing anything', async () => {
  const dir = await project();
  try {
    const report = await run(dir, { dryRun: true });
    assert.equal(report.dryRun, true);
    assert.equal(await pathExists(path.join(dir, 'out')), false);
    assert.equal(await pathExists(path.join(dir, 'build-manifest.json')), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a dependency outside the source tree is fingerprinted too', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-contract-'));
  try {
    await mkdir(path.join(dir, 'src'), { recursive: true });
    await mkdir(path.join(dir, 'shared'), { recursive: true });
    await writeFile(path.join(dir, 'shared/base.json'), '{"name":"base","level":1}\n');
    await writeFile(
      path.join(dir, 'src/data.json'),
      '{"extends":"../shared/base.json","name":"demo"}\n',
    );

    await run(dir);
    await writeFile(path.join(dir, 'shared/base.json'), '{"name":"base","level":2}\n');
    const second = await run(dir);
    assert.ok(second.built.includes('data.json'));
    assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')), {
      name: 'demo',
      level: 2,
    });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('mapLimit bounds the number of concurrent operations', async () => {
  let active = 0;
  let peak = 0;
  await mapLimit(Array.from({ length: 20 }), 3, async () => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1;
  });
  assert.equal(peak, 3);
});

test('concurrency does not change output bytes or manifest order', async () => {
  const serial = await project();
  const parallel = await project();
  try {
    await run(serial, { concurrency: 1 });
    await run(parallel, { concurrency: 4 });
    assert.deepEqual(await snapshot(parallel), await snapshot(serial));
    assert.throws(() => parseArgs(['--concurrency', '0']), /positive integer/);
  } finally {
    await rm(serial, { recursive: true, force: true });
    await rm(parallel, { recursive: true, force: true });
  }
});

test('watch rebuilds when a source file changes', async () => {
  const dir = await project();
  const reports = [];
  let close;
  try {
    close = await startWatch(options({ watch: true }), dir, {
      onReport: (report) => reports.push(report),
      onError: (error) => {
        throw error;
      },
    });
    assert.ok(reports.length >= 1);

    await writeFile(path.join(dir, 'src/b.js'), "export const b = 'WATCH';\n");
    await waitForReport(reports, (report) => report.built.includes('b.js'), 1);
    assert.match(await readFile(path.join(dir, 'out/b.js'), 'utf8'), /WATCH/);

    await mkdir(path.join(dir, 'src/newdir'), { recursive: true });
    await writeFile(path.join(dir, 'src/newdir/new.js'), 'export const fresh = 1;\n');
    await waitForReport(reports, (report) => report.built.includes('newdir/new.js'), 1);
    assert.ok(await exists(path.join(dir, 'out/newdir/new.js')));

    await unlink(path.join(dir, 'src/newdir/new.js'));
    await waitForReport(reports, (report) => report.removed.includes('newdir/new.js'), 1);
    assert.equal(await exists(path.join(dir, 'out/newdir/new.js')), false);
  } finally {
    if (close) await close();
    await rm(dir, { recursive: true, force: true });
  }
});
