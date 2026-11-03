import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { cp, mkdir, mkdtemp, open, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SKIP = new Set(['out', 'node_modules', 'build-manifest.json']);

// Copy the project under test into a scratch directory so builds never touch
// the repository itself.
async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-visible-'));
  await cp(ROOT, dir, {
    recursive: true,
    filter: (src) => {
      const rel = path.relative(ROOT, src);
      if (rel === '') return true;
      return !SKIP.has(rel.split(path.sep)[0]);
    },
  });
  return dir;
}

// Run the CLI with its output redirected to a file descriptor instead of a
// pipe, so the child never needs a pipe on any platform.
async function run(dir, args = []) {
  const logPath = path.join(dir, '.build.log');
  const handle = await open(logPath, 'w');
  try {
    const child = spawn(process.execPath, [path.join(dir, 'bin', 'build.js'), ...args], {
      cwd: dir,
      stdio: ['ignore', handle.fd, handle.fd],
    });
    const code = await new Promise((resolve, reject) => {
      child.on('error', reject);
      child.on('close', resolve);
    });
    return { code, output: await readFile(logPath, 'utf8') };
  } finally {
    await handle.close();
  }
}

async function build(dir, args = []) {
  const result = await run(dir, ['--json', ...args]);
  assert.equal(result.code, 0, `build failed: ${result.output}`);
  const lines = result.output.trim().split('\n');
  return JSON.parse(lines[lines.length - 1]);
}

async function readManifest(dir) {
  return JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function readReports(logPath) {
  let text = '';
  try {
    text = await readFile(logPath, 'utf8');
  } catch {
    return [];
  }
  const reports = [];
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try {
      reports.push(JSON.parse(line));
    } catch {
      // A partially written final line: ignore and poll again.
    }
  }
  return reports;
}

async function waitForReport(logPath, predicate, { skip = 0, timeoutMs = 20000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const reports = await readReports(logPath);
    const found = reports.slice(skip).find(predicate);
    if (found) return found;
    if (Date.now() > deadline) {
      throw new Error(`timed out waiting for a build report; saw ${JSON.stringify(reports)}`);
    }
    await delay(50);
  }
}

async function snapshot(dir) {
  const files = {};
  const walk = async (current) => {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const abs = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(abs);
      else if (entry.isFile()) {
        files[path.relative(dir, abs).split(path.sep).join('/')] = (await readFile(abs)).toString('base64');
      }
    }
  };
  await walk(path.join(dir, 'out'));
  files['build-manifest.json'] = (await readFile(path.join(dir, 'build-manifest.json'))).toString('base64');
  return files;
}

test('build emits outputs and a v2 manifest', async () => {
  const dir = await project();
  try {
    const report = await build(dir);
    assert.ok(report.built.includes('a.js'));

    assert.match(await readFile(path.join(dir, 'out', 'a.js'), 'utf8'), /\/\/# build [0-9a-f]{8}/);
    assert.match(await readFile(path.join(dir, 'out', 'style.css'), 'utf8'), /url\(img\.[0-9a-f]{8}\.png\)/);

    const manifest = await readManifest(dir);
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
    assert.equal((await stat(path.join(dir, 'out', 'a.js'))).isFile(), true);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('changing an asset a stylesheet references through url() rebuilds the stylesheet', async () => {
  const dir = await project();
  try {
    await build(dir);
    const before = /url\((img\.[0-9a-f]{8}\.png)\)/.exec(await readFile(path.join(dir, 'out', 'style.css'), 'utf8'));
    assert.ok(before, 'expected a hashed asset reference');

    const png = path.join(dir, 'src', 'img.png');
    await writeFile(png, Buffer.concat([await readFile(png), Buffer.from('v2')]));

    const report = await build(dir);
    assert.ok(report.built.includes('style.css'), `expected style.css in ${report.built}`);

    const after = /url\((img\.[0-9a-f]{8}\.png)\)/.exec(await readFile(path.join(dir, 'out', 'style.css'), 'utf8'));
    assert.ok(after, 'expected a hashed asset reference');
    assert.notEqual(after[1], before[1]);
    assert.equal(existsSync(path.join(dir, 'out', after[1])), true);
    assert.equal(existsSync(path.join(dir, 'out', before[1])), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('changing a JSON base file rebuilds the derived file', async () => {
  const dir = await project();
  try {
    await build(dir);
    await writeFile(path.join(dir, 'src', 'base.json'), `${JSON.stringify({ name: 'base', level: 2 }, null, 2)}\n`);

    const report = await build(dir);
    assert.ok(report.built.includes('data.json'), `expected data.json in ${report.built}`);
    assert.deepEqual(JSON.parse(await readFile(path.join(dir, 'out', 'data.json'), 'utf8')), {
      name: 'demo',
      level: 2,
    });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('rewriting a source without changing its mtime still rebuilds', async () => {
  const dir = await project();
  try {
    await build(dir);
    const file = path.join(dir, 'src', 'b.js');
    const before = await stat(file);
    await writeFile(file, "export const b = 'B2';\n");
    await utimes(file, before.atime, before.mtime);

    const report = await build(dir);
    assert.ok(report.built.includes('b.js'), `expected b.js in ${report.built}`);
    assert.match(await readFile(path.join(dir, 'out', 'b.js'), 'utf8'), /B2/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('deleting a source removes its output and its manifest entry', async () => {
  const dir = await project();
  try {
    await build(dir);
    await rm(path.join(dir, 'src', 'extra.js'));

    const report = await build(dir);
    assert.deepEqual(report.removed, ['extra.js']);
    assert.equal(existsSync(path.join(dir, 'out', 'extra.js')), false);
    assert.equal('extra.js' in (await readManifest(dir)).files, false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a manifest that names a missing output heals itself', async () => {
  const dir = await project();
  try {
    await build(dir);
    await rm(path.join(dir, 'out', 'a.js'));

    const report = await build(dir);
    assert.ok(report.built.includes('a.js'), `expected a.js in ${report.built}`);
    assert.match(await readFile(path.join(dir, 'out', 'a.js'), 'utf8'), /\/\/# build [0-9a-f]{8}/);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('a corrupt or half-written manifest does not crash the next build', async () => {
  const dir = await project();
  try {
    await build(dir);
    const manifestPath = path.join(dir, 'build-manifest.json');
    for (const broken of ['{"version": 2, "files": {', '{"version":2}', 'null', '{"version":1,"files":{}}']) {
      await writeFile(manifestPath, broken);
      const report = await build(dir);
      assert.ok(report.built.length > 0, `expected a rebuild after ${broken}`);
      const manifest = await readManifest(dir);
      assert.equal(manifest.version, 2);
      assert.ok(manifest.files['a.js']);
    }
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
    assert.equal(existsSync(path.join(dir, 'out')), false);
    assert.equal(existsSync(path.join(dir, 'build-manifest.json')), false);
    assert.equal((await readdir(dir)).some((name) => name.endsWith('.tmp')), false);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--concurrency bounds the build without changing output bytes', async () => {
  const one = await project();
  const many = await project();
  try {
    await build(one, ['--concurrency', '1']);
    await build(many, ['--concurrency', '3']);
    assert.deepEqual(await snapshot(one), await snapshot(many));

    for (const args of [['--concurrency', '0'], ['--concurrency', 'x'], ['--concurrency']]) {
      const result = await run(one, ['--json', ...args]);
      assert.equal(result.code, 1, `expected failure for ${args.join(' ')}`);
      assert.match(result.output, /--concurrency/);
    }
  } finally {
    await rm(one, { recursive: true, force: true });
    await rm(many, { recursive: true, force: true });
  }
});

test('a nested stylesheet emits its asset next to the stylesheet output', async () => {
  const dir = await project();
  try {
    await mkdir(path.join(dir, 'src', 'css'), { recursive: true });
    await writeFile(path.join(dir, 'src', 'css', 'theme.css'), '.t { background: url(../img.png); }\n');

    await build(dir);
    const css = await readFile(path.join(dir, 'out', 'css', 'theme.css'), 'utf8');
    const name = /url\((img\.[0-9a-f]{8}\.png)\)/.exec(css);
    assert.ok(name, `expected a hashed reference in ${css}`);
    assert.equal(existsSync(path.join(dir, 'out', 'css', name[1])), true);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test('--watch rebuilds when a source changes', async () => {
  const dir = await project();
  const logPath = path.join(dir, '.watch.log');
  const handle = await open(logPath, 'w');
  const child = spawn(process.execPath, [path.join(dir, 'bin', 'build.js'), '--watch', '--json'], {
    cwd: dir,
    stdio: ['ignore', handle.fd, handle.fd],
  });
  try {
    await waitForReport(logPath, (report) => Array.isArray(report.built));
    await writeFile(path.join(dir, 'src', 'b.js'), "export const b = 'B2';\n");
    const report = await waitForReport(logPath, (candidate) => candidate.built.includes('b.js'), {
      skip: 1,
    });
    assert.ok(report.built.includes('b.js'));
    assert.match(await readFile(path.join(dir, 'out', 'b.js'), 'utf8'), /B2/);
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      const closed = new Promise((resolve) => child.once('close', resolve));
      child.kill();
      await closed;
    }
    await handle.close();
    await rm(dir, { recursive: true, force: true });
  }
});
