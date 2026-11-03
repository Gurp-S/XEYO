// A/B probe: runs the same defect scenarios against a code root and prints one
// line per scenario. Builds run in-process (no child stdio); only --watch uses a
// detached child with stdio: 'ignore' and is verified through the output tree.
// Usage: node tests/ab/probe.mjs [--code <dir>]
import { cp, mkdir, mkdtemp, readFile, readdir, rm, stat, utimes, writeFile } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..');
const argv = process.argv.slice(2);
const codeIdx = argv.indexOf('--code');
const CODE = path.resolve(codeIdx >= 0 ? argv[codeIdx + 1] : repoRoot);

const FIXTURES = {
  'a.js': "import './b.js';\nexport const a = 1;\n",
  'b.js': 'export const b = 2;\n',
  'extra.js': 'export const extra = 3;\n',
  'img.png': 'PNG-ONE',
  'img2.png': 'PNG-TWO',
  'style.css': '.x { background: url(./img.png); }\n',
  'base.json': '{"base": true, "shared": 1}\n',
  'data.json': '{"extends": "./base.json", "own": 2}\n',
  'note.txt': 'hello\n',
};

// The code root is copied per scenario so a build's own state never leaks across.
async function loadCode() {
  return import(pathToFileURL(path.join(CODE, 'lib/build.js')).href);
}

async function seed(dir) {
  await mkdir(path.join(dir, 'src'), { recursive: true });
  for (const [name, body] of Object.entries(FIXTURES)) {
    await writeFile(path.join(dir, 'src', name), body);
  }
}

async function build(dir, extra = []) {
  const { build: run, parseArgs } = await loadCode();
  return run(parseArgs(['--json', ...extra]), dir);
}

async function manifest(dir) {
  return JSON.parse(await readFile(path.join(dir, 'build-manifest.json'), 'utf8'));
}

async function tree(dir) {
  const out = {};
  async function walk(abs, rel) {
    for (const entry of await readdir(abs, { withFileTypes: true })) {
      const nextRel = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) await walk(path.join(abs, entry.name), nextRel);
      else out[nextRel] = (await readFile(path.join(abs, entry.name))).toString('base64');
    }
  }
  await walk(dir, '');
  return out;
}

const exists = (p) => stat(p).then(() => true, () => false);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const scenarios = {
  // Defect 1a: a css url() target is not tracked as a dependency.
  async 'css-url-dependency'(dir) {
    await seed(dir);
    await build(dir);
    const first = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    await writeFile(path.join(dir, 'src/img.png'), 'PNG-THREE');
    const report = await build(dir);
    const second = await readFile(path.join(dir, 'out/style.css'), 'utf8');
    const name = second.match(/url\((img\.[0-9a-f]{8}\.png)\)/)?.[1];
    const ok = report.built.includes('style.css') && first !== second && Boolean(name) && (await exists(path.join(dir, 'out', name)));
    return { ok, detail: { built: report.built, first, second } };
  },

  // Defect 1b: a json extends base is not tracked as a dependency.
  async 'json-extends-dependency'(dir) {
    await seed(dir);
    await build(dir);
    const first = await readFile(path.join(dir, 'out/data.json'), 'utf8');
    await writeFile(path.join(dir, 'src/base.json'), '{"base": "changed", "shared": 1}\n');
    const report = await build(dir);
    const second = await readFile(path.join(dir, 'out/data.json'), 'utf8');
    const ok = report.built.includes('data.json') && first !== second && second.includes('changed');
    return { ok, detail: { built: report.built, first, second } };
  },

  // Defect 2: a same-size rewrite with a restored mtime is invisible to stat().
  async 'same-mtime-rewrite'(dir) {
    await seed(dir);
    await build(dir);
    const file = path.join(dir, 'src/a.js');
    const outFile = path.join(dir, 'out/a.js');
    const before = await readFile(outFile, 'utf8');
    const info = await stat(file);
    await writeFile(file, (await readFile(file, 'utf8')).replace('= 1', '= 9'));
    await utimes(file, info.atime, info.mtime);
    const report = await build(dir);
    const after = await readFile(outFile, 'utf8');
    const ok = report.built.includes('a.js') && before !== after;
    return { ok, detail: { built: report.built, before, after } };
  },

  // Defect 3a: deleting a source must remove its output and its manifest entry.
  async 'deleted-source-cleanup'(dir) {
    await seed(dir);
    await build(dir);
    await rm(path.join(dir, 'src/extra.js'));
    const report = await build(dir);
    const m = await manifest(dir);
    const ok = !(await exists(path.join(dir, 'out/extra.js'))) && !('extra.js' in m.files);
    return { ok, detail: { removed: report.removed, files: Object.keys(m.files) } };
  },

  // Defect 3b: a manifest naming an output that no longer exists must heal.
  async 'missing-output-heals'(dir) {
    await seed(dir);
    await build(dir);
    await rm(path.join(dir, 'out/a.js'));
    const report = await build(dir);
    const ok = (await exists(path.join(dir, 'out/a.js'))) && report.built.includes('a.js');
    return { ok, detail: { built: report.built } };
  },

  // Defect 3c: a css asset that is no longer referenced must not linger.
  async 'stale-css-asset-removed'(dir) {
    await seed(dir);
    await build(dir);
    const before = await readdir(path.join(dir, 'out'));
    await writeFile(path.join(dir, 'src/style.css'), '.x { background: url(./img2.png); }\n');
    await build(dir);
    const after = await readdir(path.join(dir, 'out'));
    const ok = after.some((n) => /^img2\.[0-9a-f]{8}\.png$/.test(n)) && !after.some((n) => /^img\.[0-9a-f]{8}\.png$/.test(n));
    return { ok, detail: { before, after } };
  },

  // Defect 4: a half-written manifest must not break the next build.
  async 'torn-manifest'(dir) {
    await seed(dir);
    await build(dir);
    await writeFile(path.join(dir, 'build-manifest.json'), '{"version": 2, "files": {');
    const report = await build(dir);
    const m = await manifest(dir);
    const ok = m.version === 2 && Boolean(m.files['a.js']) && (await exists(path.join(dir, 'out/a.js')));
    return { ok, detail: { built: report.built } };
  },

  // Defect 4b: a syntactically valid but shape-less manifest must not crash.
  async 'empty-manifest-shape'(dir) {
    await seed(dir);
    await build(dir);
    await writeFile(path.join(dir, 'build-manifest.json'), '{"version": 2}');
    const report = await build(dir);
    const m = await manifest(dir);
    const ok = Boolean(m.files?.['a.js']) && report.built.includes('a.js');
    return { ok, detail: { built: report.built } };
  },

  // Contract: incremental output equals a from-scratch build, byte for byte.
  async 'incremental-equals-clean'(dir) {
    await seed(dir);
    await build(dir);
    await writeFile(path.join(dir, 'src/img.png'), 'PNG-FOUR');
    await writeFile(path.join(dir, 'src/b.js'), 'export const b = 42;\n');
    await rm(path.join(dir, 'src/note.txt'));
    await writeFile(path.join(dir, 'src/new.txt'), 'new\n');
    await build(dir);
    const incremental = await tree(path.join(dir, 'out'));
    const clean = await mkdtemp(path.join(tmpdir(), 'mini-build-clean-'));
    try {
      await cp(path.join(dir, 'src'), path.join(clean, 'src'), { recursive: true });
      await build(clean);
      const fresh = await tree(path.join(clean, 'out'));
      const ok = JSON.stringify(incremental) === JSON.stringify(fresh);
      const diff = Object.keys({ ...incremental, ...fresh }).filter((k) => incremental[k] !== fresh[k]);
      return { ok, detail: { diff } };
    } finally {
      await rm(clean, { recursive: true, force: true });
    }
  },

  // Feature: --concurrency bounds parallelism without changing the output.
  async 'concurrency-parity'(dir) {
    await seed(dir);
    const one = await build(dir, ['--concurrency', '1']);
    const oneTree = await tree(path.join(dir, 'out'));
    await rm(path.join(dir, 'out'), { recursive: true, force: true });
    await rm(path.join(dir, 'build-manifest.json'));
    const four = await build(dir, ['--concurrency', '4']);
    const fourTree = await tree(path.join(dir, 'out'));
    const ok = one.built.length === four.built.length && JSON.stringify(oneTree) === JSON.stringify(fourTree);
    return { ok, detail: { one: one.built, four: four.built } };
  },

  // Feature: --concurrency must reject a bad value.
  async 'concurrency-validation'(dir) {
    await seed(dir);
    const { parseArgs } = await loadCode();
    const rejected = [];
    for (const value of ['0', '-2', 'abc', '1.5']) {
      let threw = false;
      try {
        parseArgs(['--concurrency', value]);
      } catch {
        threw = true;
      }
      rejected.push([value, threw]);
    }
    const ok = rejected.every(([, threw]) => threw);
    return { ok, detail: { rejected } };
  },

  // Feature: --watch rebuilds when a source changes.
  async 'watch-rebuilds'(dir) {
    await seed(dir);
    await build(dir);
    const child = spawn(process.execPath, ['bin/build.js', '--watch'], { cwd: dir, stdio: 'ignore' });
    const outFile = path.join(dir, 'out/b.js');
    const poll = async (pattern, ms) => {
      const until = Date.now() + ms;
      while (Date.now() < until) {
        const text = await readFile(outFile, 'utf8').catch(() => '');
        if (pattern.test(text)) return true;
        await wait(50);
      }
      return false;
    };
    try {
      const started = await poll(/export const b = 2;/, 10000);
      if (!started) return { ok: false, detail: { reason: 'no initial build' } };
      await writeFile(path.join(dir, 'src/b.js'), 'export const b = 77;\n');
      const rebuilt = await poll(/export const b = 77;/, 10000);
      return { ok: rebuilt, detail: { started, rebuilt } };
    } finally {
      child.kill();
      // On Windows the killed child still holds its cwd for a moment; wait for
      // the exit so the scenario's temp dir can be removed.
      await Promise.race([new Promise((r) => child.once('exit', r)), wait(3000)]);
    }
  },
};

const results = [];
for (const [name, fn] of Object.entries(scenarios)) {
  const dir = await mkdtemp(path.join(tmpdir(), 'mini-build-ab-'));
  try {
    await cp(path.join(CODE, 'bin'), path.join(dir, 'bin'), { recursive: true });
    await cp(path.join(CODE, 'lib'), path.join(dir, 'lib'), { recursive: true });
    await cp(path.join(CODE, 'package.json'), path.join(dir, 'package.json'));
    results.push({ scenario: name, ...(await fn(dir)) });
  } catch (error) {
    results.push({ scenario: name, ok: false, detail: { error: String(error?.message ?? error) } });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const passed = results.filter((r) => r.ok).length;
for (const r of results) {
  process.stdout.write(`${r.ok ? 'PASS' : 'FAIL'} ${r.scenario}${r.ok ? '' : ` ${JSON.stringify(r.detail)}`}\n`);
}
process.stdout.write(`${passed}/${results.length} passed (code: ${CODE})\n`);
process.exitCode = passed === results.length ? 0 : 1;
