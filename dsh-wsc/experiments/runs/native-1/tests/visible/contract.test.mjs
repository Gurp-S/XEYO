import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdtemp, readdir, readFile, rm, stat, symlink, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build as runBuild, parseArgs } from '../../lib/build.js';
import { watchBuild } from '../../lib/watch.js';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-contract-'));
  await cp(repoRoot, dir, {
    recursive: true,
    filter: (src) => !/[\\/](out|node_modules)([\\/]|$)/.test(src) && !src.endsWith('build-manifest.json'),
  });
  return dir;
}

async function build(dir, args = []) {
  return runBuild(parseArgs(args), dir);
}

function failure(args) {
  try {
    parseArgs(args);
  } catch (err) {
    return err;
  }
  assert.fail(`expected mini-build to reject ${args.join(' ')}`);
}

async function manifestOf(dir) {
  return JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
}

async function exists(abs) {
  try {
    await stat(abs);
    return true;
  } catch {
    return false;
  }
}

/** Every file below `root`, keyed by relative path, as base64 content. */
async function tree(root) {
  const files = {};
  async function walk(rel) {
    for (const entry of await readdir(path.join(root, rel), { withFileTypes: true })) {
      const child = rel ? path.posix.join(rel, entry.name) : entry.name;
      if (entry.isDirectory()) await walk(child);
      else files[child] = (await readFile(path.join(root, child))).toString('base64');
    }
  }
  await walk('');
  return files;
}

function startWatch(dir) {
  const reports = [];
  const listeners = [];
  let error = null;

  const notify = () => {
    for (const listener of listeners.splice(0)) listener();
  };

  const watcher = watchBuild(parseArgs(['--watch']), dir, {
    onReport: (report) => {
      reports.push(report);
      notify();
    },
    onError: (err) => {
      error = err;
      notify();
    },
  });
  watcher.catch((err) => {
    error = err;
    notify();
  });

  const waitFor = (count, ms = 20000) =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`timed out waiting for report ${count}; got ${reports.length}`));
      }, ms);
      const check = () => {
        if (error) {
          clearTimeout(timer);
          reject(error);
        } else if (reports.length >= count) {
          clearTimeout(timer);
          resolve(reports[count - 1]);
        } else {
          listeners.push(check);
        }
      };
      check();
    });

  const stop = async () => {
    try {
      await (await watcher).close();
    } catch {
      /* the build already reported its failure */
    }
  };

  return { reports, waitFor, stop };
}

test('a stylesheet rebuilds when an asset it references through url() changes', async () => {
  const dir = await project();
  try {
    await build(dir);
    const before = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const oldName = /url\((img\.[0-9a-f]{8}\.png)\)/.exec(before)[1];

    await writeFile(path.join(dir, 'src/img.png'), Buffer.from('different-image-bytes'));
    const report = await build(dir);

    assert.ok(report.built.includes('style.css'), `style.css not rebuilt: ${JSON.stringify(report.built)}`);
    const after = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const newName = /url\((img\.[0-9a-f]{8}\.png)\)/.exec(after)[1];
    assert.notEqual(newName, oldName);
    assert.ok(await exists(path.join(dir, 'out', newName)));
    assert.equal(await exists(path.join(dir, 'out', oldName)), false, 'stale hashed asset left behind');
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a JSON file rebuilds when a file it extends changes', async () => {
  const dir = await project();
  try {
    await writeFile(path.join(dir, 'src/base.json'), '{"shared":"old"}\n');
    await writeFile(path.join(dir, 'src/data.json'), '{"extends":"./base.json","name":"demo"}\n');
    await build(dir);
    assert.equal(JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8')).shared, 'old');

    await writeFile(path.join(dir, 'src/base.json'), '{"shared":"new"}\n');
    const report = await build(dir);

    assert.ok(report.built.includes('data.json'), `data.json not rebuilt: ${JSON.stringify(report.built)}`);
    const merged = JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8'));
    assert.equal(merged.shared, 'new');
    assert.equal(merged.name, 'demo');
    assert.equal(merged.extends, undefined);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a rewrite that keeps the mtime still rebuilds from the new content', async () => {
  const dir = await project();
  try {
    const bPath = path.join(dir, 'src/b.js');
    await writeFile(bPath, "export const b = 'B1';\n");
    await build(dir);
    const { atime, mtime, mtimeMs } = await stat(bPath);

    await writeFile(bPath, "export const b = 'B2';\n");
    await utimes(bPath, atime, mtime);
    assert.ok(Math.abs((await stat(bPath)).mtimeMs - mtimeMs) < 2, 'mtime was not preserved');

    const report = await build(dir);
    assert.ok(report.built.includes('b.js'), `b.js not rebuilt: ${JSON.stringify(report.built)}`);
    assert.ok(report.built.includes('a.js'), 'dependent a.js not rebuilt');
    assert.match(await readFile(path.join(dir, 'out/b.js'), 'utf8'), /B2/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('deleting a source removes its output and its manifest entry', async () => {
  const dir = await project();
  try {
    await build(dir);
    assert.ok(await exists(path.join(dir, 'out/extra.js')));

    await rm(path.join(dir, 'src/extra.js'));
    const report = await build(dir);

    assert.deepEqual(report.removed, ['extra.js']);
    assert.equal(await exists(path.join(dir, 'out/extra.js')), false);
    assert.equal((await manifestOf(dir)).files['extra.js'], undefined);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a manifest entry whose output disappeared is rebuilt', async () => {
  const dir = await project();
  try {
    await build(dir);
    await rm(path.join(dir, 'out/a.js'));

    const report = await build(dir);
    assert.ok(report.built.includes('a.js'), `a.js not rebuilt: ${JSON.stringify(report.built)}`);
    assert.ok(await exists(path.join(dir, 'out/a.js')));
    assert.ok((await manifestOf(dir)).files['a.js']);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a half-written manifest does not break the next build', async () => {
  const dir = await project();
  try {
    await build(dir);
    await writeFile(path.join(dir, 'build-manifest.json'), '{"version": 2, "files": {"a.js": {"key": "ab');

    const report = await build(dir);
    assert.ok(report.built.includes('a.js'), `a.js not rebuilt: ${JSON.stringify(report.built)}`);
    const manifest = await manifestOf(dir);
    assert.equal(manifest.version, 2);
    assert.ok(manifest.files['a.js']);
    assert.match(await readFile(path.join(dir, 'out/a.js'), 'utf8'), /\/\/# build [0-9a-f]{8}/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--dry-run writes nothing at all', async () => {
  const dir = await project();
  try {
    const report = await build(dir, ['--dry-run']);
    assert.equal(report.dryRun, true);
    assert.ok(report.built.length > 0);
    assert.equal(await exists(path.join(dir, 'out')), false);
    assert.equal(await exists(path.join(dir, 'build-manifest.json')), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--concurrency does not change the report or the bytes', async () => {
  const one = await project();
  const many = await project();
  try {
    const serial = await build(one, ['--concurrency', '1']);
    const parallel = await build(many, ['--concurrency', '4']);
    assert.deepEqual(serial.built, parallel.built);
    assert.deepEqual(serial.skipped, parallel.skipped);
    assert.deepEqual(serial.outputs, parallel.outputs);
    assert.deepEqual(await tree(path.join(one, 'out')), await tree(path.join(many, 'out')));
    assert.equal(
      await readFile(path.join(one, 'build-manifest.json'), 'utf8'),
      await readFile(path.join(many, 'build-manifest.json'), 'utf8'),
    );
  } finally {
    await rm(one, { recursive: true, force: true });
    await rm(many, { recursive: true, force: true });
  }
});

test('--concurrency rejects values that are not positive integers', async () => {
  const dir = await project();
  try {
    for (const value of ['0', '-1', '1.5', 'many']) {
      const err = failure(['--concurrency', value]);
      assert.match(err.message, /--concurrency needs a positive integer/);
    }
    const err = failure(['--concurrency']);
    assert.match(err.message, /--concurrency needs a value/);
    assert.equal(await exists(path.join(dir, 'out')), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('symlinked sources are skipped instead of followed', async (t) => {
  const dir = await project();
  try {
    try {
      await symlink('a.js', path.join(dir, 'src/link.js'), 'file');
    } catch {
      t.skip('symlinks are unavailable here');
      return;
    }
    const report = await build(dir);
    assert.equal(report.built.includes('link.js'), false);
    assert.equal(await exists(path.join(dir, 'out/link.js')), false);
    assert.ok(await exists(path.join(dir, 'out/a.js')));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--watch rebuilds after a source changes', async () => {
  const dir = await project();
  const watcher = startWatch(dir);
  try {
    const first = await watcher.waitFor(1);
    assert.ok(first.built.length > 0);
    const before = await readFile(path.join(dir, 'out/b.js'), 'utf8');

    await writeFile(path.join(dir, 'src/b.js'), "export const b = 'B2';\n");
    const second = await watcher.waitFor(2);

    assert.ok(second.built.includes('b.js'), `b.js not rebuilt: ${JSON.stringify(second.built)}`);
    const after = await readFile(path.join(dir, 'out/b.js'), 'utf8');
    assert.notEqual(after, before);
    assert.match(after, /B2/);
  } finally {
    await watcher.stop();
    await rm(dir, { recursive: true, force: true });
  }
});
