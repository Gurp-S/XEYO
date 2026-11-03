import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, writeFile, rm, utimes, stat, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const run = promisify(execFile);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = process.env.MINI_BUILD_ROOT
  ? path.resolve(process.env.MINI_BUILD_ROOT)
  : path.resolve(here, '..', 'fixture');

async function project() {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-hidden-'));
  await cp(repoRoot, dir, {
    recursive: true,
    filter: (src) =>
      !/[\\/](out|node_modules|\.git)([\\/]|$)/.test(src) && !src.endsWith('build-manifest.json'),
  });
  return dir;
}

async function build(dir, args = []) {
  const { stdout } = await run(process.execPath, ['bin/build.js', '--json', ...args], { cwd: dir });
  return JSON.parse(stdout);
}

async function snapshot(root) {
  const out = {};
  async function walk(dir, base) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const abs = path.join(dir, entry.name);
      const rel = path.relative(base, abs).split(path.sep).join('/');
      if (entry.isDirectory()) await walk(abs, base);
      else out[rel] = (await readFile(abs)).toString('base64');
    }
  }
  await walk(root, root);
  return out;
}

function sha(text) {
  return createHash('sha1').update(text).digest('hex').slice(0, 8);
}

const cases = [];
function withProject(name, body) {
  cases.push([name, body]);
}

withProject('css url() target change rebuilds the stylesheet', async (dir) => {
  await build(dir);
  const before = await readFile(path.join(dir, 'out/style.css'), 'utf8');
  const img = path.join(dir, 'src/img.png');
  await writeFile(img, Buffer.concat([await readFile(img), Buffer.from([0])]));
  await build(dir);
  const after = await readFile(path.join(dir, 'out/style.css'), 'utf8');
  assert.notEqual(after, before);
  const target = /url\(([^)]+)\)/.exec(after)[1].trim();
  assert.deepEqual(await readFile(path.join(dir, 'out', target)), await readFile(img));
});

withProject('json extends base change rebuilds the derived file', async (dir) => {
  await build(dir);
  const base = path.join(dir, 'src/base.json');
  const parsed = JSON.parse(await readFile(base, 'utf8'));
  parsed.level = 2;
  await writeFile(base, `${JSON.stringify(parsed, null, 2)}\n`);
  await build(dir);
  const out = JSON.parse(await readFile(path.join(dir, 'out/data.json'), 'utf8'));
  assert.equal(out.level, 2);
  assert.equal(out.name, 'demo');
});

withProject('content change with an unchanged mtime is rebuilt', async (dir) => {
  await build(dir);
  const file = path.join(dir, 'src/a.js');
  const original = await readFile(file, 'utf8');
  const info = await stat(file);
  const edited = original.replace("'AAA'", "'AAB'");
  assert.notEqual(edited, original);
  await writeFile(file, edited);
  await utimes(file, info.atime, info.mtime);
  await build(dir);
  const outText = await readFile(path.join(dir, 'out/a.js'), 'utf8');
  assert.match(outText, new RegExp(`//# build ${sha(edited)}`));
});

withProject('deleting a source removes its output and manifest entry', async (dir) => {
  await build(dir);
  await rm(path.join(dir, 'src/extra.js'));
  await build(dir);
  await assert.rejects(readFile(path.join(dir, 'out/extra.js')), /ENOENT/);
  const manifest = JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
  assert.equal(manifest.files['extra.js'], undefined);
});

withProject('a manifest that claims missing outputs self-heals', async (dir) => {
  await build(dir);
  await rm(path.join(dir, 'out/a.js'));
  await build(dir);
  assert.match(await readFile(path.join(dir, 'out/a.js'), 'utf8'), /\/\/# build [0-9a-f]{8}/);
});

withProject('a transitive js dependency change rebuilds the importer', async (dir) => {
  await build(dir);
  await writeFile(path.join(dir, 'src/b.js'), "export const b = 'B2';\n");
  const report = await build(dir);
  assert.ok(report.built.includes('a.js'));
  assert.match(await readFile(path.join(dir, 'out/a.js'), 'utf8'), new RegExp(`//# build ${sha(
    await readFile(path.join(dir, 'src/a.js'), 'utf8'),
  )}`));
});

withProject('--concurrency and --watch are supported', async (dir) => {
  const help = await run(process.execPath, ['bin/build.js', '--help'], { cwd: dir });
  assert.match(help.stdout, /--concurrency/);
  assert.match(help.stdout, /--watch/);
  await build(dir, ['--concurrency', '4']);
  const parallel = await snapshot(path.join(dir, 'out'));
  const other = await project();
  try {
    await build(other);
    assert.deepEqual(parallel, await snapshot(path.join(other, 'out')));
  } finally {
    await rm(other, { recursive: true, force: true });
  }
});

withProject('--watch rebuilds after a source change', async (dir) => {
  await build(dir);
  const child = spawn(process.execPath, ['bin/build.js', '--watch'], { cwd: dir });
  let buffer = '';
  child.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
  });
  const waitFor = (re, from, ms) =>
    new Promise((resolve, reject) => {
      const started = Date.now();
      const tick = () => {
        if (re.test(buffer.slice(from))) return resolve(true);
        if (Date.now() - started > ms) {
          return reject(new Error(`timed out waiting for ${re}; tail=${JSON.stringify(buffer.slice(-200))}`));
        }
        setTimeout(tick, 50);
      };
      tick();
    });
  try {
    await waitFor(/watch/i, 0, 15000);
    const mark = buffer.length;
    await writeFile(path.join(dir, 'src/b.js'), "export const b = 'B3';\n");
    await waitFor(/built/i, mark, 15000);
  } finally {
    child.kill();
    if (child.exitCode === null && child.signalCode === null) {
      await new Promise((resolve) => child.once('exit', resolve));
    }
  }
});

withProject('contract: dry-run, manifest shape, determinism, zero deps', async (dir) => {
  await build(dir, ['--dry-run']);
  await assert.rejects(stat(path.join(dir, 'out')), /ENOENT/);
  await assert.rejects(stat(path.join(dir, 'build-manifest.json')), /ENOENT/);

  await build(dir);
  const manifest = JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
  assert.equal(manifest.version, 2);
  assert.deepEqual(Object.keys(manifest.files).sort(), [
    'a.js',
    'b.js',
    'base.json',
    'data.json',
    'extra.js',
    'img.png',
    'style.css',
  ]);
  for (const entry of Object.values(manifest.files)) {
    assert.equal(typeof entry.key, 'string');
    assert.equal(typeof entry.deps, 'object');
    assert.ok(Array.isArray(entry.out));
  }

  const first = await snapshot(path.join(dir, 'out'));
  await rm(path.join(dir, 'out'), { recursive: true, force: true });
  await rm(path.join(dir, 'build-manifest.json'));
  await build(dir);
  assert.deepEqual(await snapshot(path.join(dir, 'out')), first);

  await build(dir, ['--out', 'dist']);
  assert.match(await readFile(path.join(dir, 'dist/a.js'), 'utf8'), /\/\/# build [0-9a-f]{8}/);
  await assert.rejects(build(dir, ['--nope']), /unknown argument/);

  const pkg = JSON.parse(await readFile(path.join(dir, 'package.json'), 'utf8'));
  assert.equal(pkg.dependencies, undefined);
  assert.equal(pkg.devDependencies, undefined);
});

for (const [name, body] of cases) {
  test(name, async () => {
    const dir = await project();
    try {
      await body(dir);
    } finally {
      await rm(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    }
  });
}
