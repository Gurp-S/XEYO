import { mkdir, readFile, rm, rmdir, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { mapLimit } from './concurrency.js';
import { cacheKey, sha1 } from './cache.js';
import { depsFromText, URL_RE } from './graph.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { walk, walkDirs } from './walk.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 1;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    maximum simultaneous file builds (default: 1)
  --watch              rebuild whenever a source file changes
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --help, -h           show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: DEFAULT_CONCURRENCY,
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
    else if (arg === '--concurrency') {
      const value = argv[(index += 1)];
      if (value === undefined) throw new Error('--concurrency needs a value');
      const parsed = Number(value);
      if (!Number.isInteger(parsed) || parsed < 1) {
        throw new Error(`--concurrency needs a positive integer, got: ${value}`);
      }
      opts.concurrency = parsed;
    } else if (arg === '--watch') opts.watch = true;
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  return opts;
}

function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha1(bytes).slice(0, 8)}${ext}`;
}

// An output name is usable only when it stays inside the output directory.
function safeOutputName(name) {
  if (typeof name !== 'string' || name === '') return false;
  if (path.posix.isAbsolute(name) || path.isAbsolute(name)) return false;
  const normalized = path.posix.normalize(name);
  return normalized !== '.' && normalized !== '..' && !normalized.startsWith('../');
}

async function isFile(abs) {
  try {
    return (await stat(abs)).isFile();
  } catch {
    return false;
  }
}

function depsChanged(prevDeps, nextDeps) {
  const names = new Set([...Object.keys(prevDeps), ...Object.keys(nextDeps)]);
  for (const name of names) {
    if (prevDeps[name] !== nextDeps[name]) return true;
  }
  return false;
}

async function isDirty(key, deps, prev, outDir) {
  if (!prev || prev.key !== key) return true;
  if (prev.out.length === 0) return true;
  if (depsChanged(prev.deps, deps)) return true;
  for (const name of prev.out) {
    if (!safeOutputName(name)) return true;
    if (!(await isFile(path.join(outDir, name)))) return true;
  }
  return false;
}

async function pruneEmptyDirs(root) {
  const dirs = (await walkDirs(root)).reverse();
  for (const dir of dirs) {
    if (dir === root) continue;
    await rmdir(dir).catch(() => {});
  }
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;

  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const bytesByRel = new Map();
  const keys = new Map();
  await mapLimit(sources, limit, async (rel) => {
    const bytes = await readFile(path.join(srcDir, rel));
    bytesByRel.set(rel, bytes);
    keys.set(rel, cacheKey(bytes));
  });

  const deps = new Map();
  for (const rel of sources) {
    const resolved = Object.create(null);
    const ext = path.posix.extname(rel);
    if (ext === '.js' || ext === '.mjs' || ext === '.css' || ext === '.json') {
      const text = bytesByRel.get(rel).toString('utf8');
      for (const spec of depsFromText(text, ext)) {
        const target = resolveDep(rel, spec);
        if (target) resolved[target] = null;
      }
    }
    deps.set(rel, resolved);
  }
  for (const resolved of deps.values()) {
    for (const target of Object.keys(resolved)) resolved[target] = keys.get(target) ?? 'missing';
  }

  const dirty = new Set();
  await mapLimit(sources, limit, async (rel) => {
    if (await isDirty(keys.get(rel), deps.get(rel), manifest.files[rel], outDir)) dirty.add(rel);
  });

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = Object.create(null);

  for (const rel of sources) {
    const key = keys.get(rel);
    const resolved = deps.get(rel);
    if (!dirty.has(rel)) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: manifest.files[rel].out };
      continue;
    }
    const ext = path.posix.extname(rel);
    const bytes = bytesByRel.get(rel);
    const outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      const text = bytes.toString('utf8');
      outputs.set(rel, `${text.trimEnd()}\n//# build ${sha1(text).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = bytes.toString('utf8');
      const names = new Map();
      for (const match of text.matchAll(URL_RE)) {
        const spec = match[1];
        const target = resolveDep(rel, spec);
        if (!target) continue;
        const targetBytes = bytesByRel.get(target);
        if (!targetBytes) continue;
        const name = hashedName(target, targetBytes);
        names.set(spec, name);
        const asset = path.posix.join(path.posix.dirname(rel), name);
        outputs.set(asset, targetBytes);
        if (!outNames.includes(asset)) outNames.push(asset);
      }
      outputs.set(rel, text.replace(URL_RE, (whole, spec) => (names.has(spec) ? `url(${names.get(spec)})` : whole)));
    } else if (ext === '.json') {
      const own = JSON.parse(bytes.toString('utf8'));
      let merged = own;
      if (own && typeof own === 'object' && !Array.isArray(own) && typeof own.extends === 'string') {
        const spec = own.extends;
        const target = resolveDep(rel, spec);
        const baseBytes = target ? bytesByRel.get(target) : undefined;
        if (!baseBytes) throw new Error(`${rel} extends missing file: ${spec}`);
        const base = JSON.parse(baseBytes.toString('utf8'));
        const { extends: dropped, ...rest } = own;
        merged = { ...base, ...rest };
      }
      outputs.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
    } else {
      outputs.set(rel, bytes);
    }
    built.push(rel);
    nextFiles[rel] = { key, deps: resolved, out: outNames };
  }

  const live = new Set();
  for (const rel of sources) {
    for (const name of nextFiles[rel].out) live.add(name);
  }
  const stale = new Set();
  for (const entry of Object.values(manifest.files)) {
    for (const name of entry.out) {
      if (!live.has(name) && safeOutputName(name)) stale.add(name);
    }
  }

  const removed = Object.keys(manifest.files)
    .filter((rel) => !Object.hasOwn(nextFiles, rel))
    .sort();

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    stale: [...stale].sort(),
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  const report = {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun: Boolean(opts.dryRun),
    durationMs: 0,
  };
  if (opts.dryRun) {
    report.durationMs = Date.now() - started;
    return report;
  }
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  await mkdir(plan.outDir, { recursive: true });
  if (plan.stale.length > 0) {
    await mapLimit(plan.stale, limit, async (name) => {
      await rm(path.join(plan.outDir, name), { force: true });
    });
    await pruneEmptyDirs(plan.outDir);
  }
  await mapLimit([...plan.outputs], limit, async ([rel, content]) => {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  await saveManifest(plan.manifestPath, plan.next);
  report.durationMs = Date.now() - started;
  return report;
}
