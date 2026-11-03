import { readdir, readFile, stat, mkdir, writeFile, rm } from 'node:fs/promises';
import { watch as fsWatch } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { readDeps } from './graph.js';
import { cacheKey } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    maximum parallel file transforms (default: 1)
  --watch              rebuild when the source tree changes
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --help, -h           show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: 1,
    watch: false,
    dryRun: false,
    json: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
    else if (arg === '--concurrency') opts.concurrency = Number(argv[(index += 1)]);
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  if (!Number.isInteger(opts.concurrency) || opts.concurrency < 1) {
    throw new Error('--concurrency must be a positive integer');
  }
  return opts;
}

async function walk(dir, base) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

function sha(input) {
  return createHash('sha1').update(input).digest('hex');
}

function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha(bytes).slice(0, 8)}${ext}`;
}

const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

async function mapLimit(items, limit, worker) {
  const results = new Array(items.length);
  let next = 0;
  const runners = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, async () => {
    for (;;) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  });
  await Promise.all(runners);
  return results;
}

async function allExist(outDir, names) {
  for (const name of names) {
    try {
      await stat(path.join(outDir, name));
    } catch {
      return false;
    }
  }
  return true;
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const contents = new Map();
  const keys = new Map();
  for (const rel of sources) {
    const bytes = await readFile(path.join(srcDir, rel));
    contents.set(rel, bytes);
    keys.set(rel, cacheKey(bytes));
  }

  const deps = new Map();
  for (const rel of sources) {
    const resolved = {};
    for (const spec of await readDeps(path.join(srcDir, rel), path.posix.extname(rel))) {
      const target = resolveDep(rel, spec);
      if (target && keys.has(target)) resolved[target] = keys.get(target);
    }
    deps.set(rel, resolved);
  }

  const dirtyList = [];
  const nextFiles = {};
  const skipped = [];
  for (const rel of sources) {
    const prev = manifest.files[rel];
    const resolved = deps.get(rel) ?? {};
    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const present = prev?.out ? await allExist(outDir, prev.out) : false;
    const dirty = !prev || prev.key !== keys.get(rel) || stale || !present;
    if (dirty) dirtyList.push(rel);
    else {
      skipped.push(rel);
      nextFiles[rel] = { key: prev.key, deps: resolved, out: prev.out };
    }
  }

  const transforms = await mapLimit(dirtyList, opts.concurrency, async (rel) => {
    const ext = path.posix.extname(rel);
    const bytes = contents.get(rel);
    const text = () => bytes.toString('utf8');
    if (ext === '.js' || ext === '.mjs') {
      return { rel, out: [[rel, `${text().trimEnd()}\n//# build ${sha(text()).slice(0, 8)}\n`]] };
    }
    if (ext === '.css') {
      const names = new Map();
      const assets = [];
      for (const match of text().matchAll(URL_RE)) {
        const target = match[1];
        const relTarget = resolveDep(rel, target);
        const assetBytes = contents.get(relTarget) ?? (await readFile(path.join(srcDir, relTarget)));
        const name = hashedName(relTarget, assetBytes);
        names.set(target, name);
        assets.push([name, assetBytes]);
      }
      const rewritten = text().replace(URL_RE, (whole, target) => `url(${names.get(target) ?? target})`);
      return { rel, out: [[rel, rewritten], ...assets] };
    }
    if (ext === '.json') {
      const own = JSON.parse(text());
      let merged = own;
      if (own && typeof own.extends === 'string') {
        const relBase = resolveDep(rel, own.extends);
        const base = JSON.parse(contents.get(relBase).toString('utf8'));
        const { extends: dropped, ...rest } = own;
        merged = { ...base, ...rest };
      }
      return { rel, out: [[rel, `${JSON.stringify(merged, null, 2)}\n`]] };
    }
    return { rel, out: [[rel, bytes]] };
  });

  const outputs = new Map();
  const built = [];
  for (const result of transforms) {
    built.push(result.rel);
    nextFiles[result.rel] = {
      key: keys.get(result.rel),
      deps: deps.get(result.rel) ?? {},
      out: result.out.map(([name]) => name),
    };
    for (const [name, payload] of result.out) outputs.set(name, payload);
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    removed,
    built,
    skipped,
    stale: removed.map((rel) => manifest.files[rel]),
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) {
    return {
      built: plan.built,
      skipped: plan.skipped,
      removed: plan.removed,
      outputs: plan.outputs.size,
      dryRun: true,
      durationMs: Date.now() - started,
    };
  }
  await mkdir(plan.outDir, { recursive: true });
  for (const stale of plan.stale) {
    for (const name of stale.out ?? []) await rm(path.join(plan.outDir, name), { force: true });
  }
  for (const [rel, content] of plan.outputs) {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  await saveManifest(plan.manifestPath, plan.next);
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun: false,
    durationMs: Date.now() - started,
  };
}

export function watch(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  let running = false;
  let pending = false;
  let timer;
  const runOnce = async () => {
    if (running) {
      pending = true;
      return;
    }
    running = true;
    try {
      const report = await build(opts, cwd);
      process.stdout.write(
        `rebuilt ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`,
      );
    } catch (error) {
      process.stderr.write(`build failed: ${error instanceof Error ? error.message : String(error)}\n`);
    } finally {
      running = false;
      if (pending) {
        pending = false;
        setImmediate(runOnce);
      }
    }
  };
  return new Promise((resolve) => {
    process.stdout.write(`watching ${path.relative(cwd, srcDir) || '.'} for changes\n`);
    void runOnce();
    const watcher = fsWatch(srcDir, { recursive: true }, () => {
      clearTimeout(timer);
      timer = setTimeout(() => void runOnce(), 100);
    });
    watcher.on('error', () => {
      clearTimeout(timer);
      watcher.close();
      resolve();
    });
  });
}
