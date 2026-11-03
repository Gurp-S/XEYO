import { readdir, readFile, stat, mkdir, writeFile, rm, rmdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { specifiersFor, URL_RE } from './graph.js';
import { fingerprint } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { mapLimit } from './concurrency.js';
import { createOwned } from './owned.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 4;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>        source directory (default: src)
  --out <dir>        output directory (default: out)
  --manifest <file>  build manifest path (default: build-manifest.json)
  --concurrency <n>  build at most n files at once (default: ${DEFAULT_CONCURRENCY})
  --watch            rebuild whenever a source file changes (Ctrl+C to stop)
  --dry-run          report the plan without writing anything
  --json             print a machine-readable report
  --help, -h         show this help
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
    else if (arg === '--concurrency') opts.concurrency = parseConcurrency(argv[(index += 1)]);
    else if (arg === '--watch') opts.watch = true;
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

function parseConcurrency(raw) {
  if (raw === undefined) throw new Error('--concurrency needs a value');
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`--concurrency needs a positive integer, got: ${raw}`);
  }
  return value;
}

async function walk(dir, base, isOwned) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (isOwned(abs)) continue;
    if (entry.isDirectory()) files.push(...(await walk(abs, base, isOwned)));
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

/** Relative output paths are untrusted manifest data: never escape `outDir`. */
function outPath(outDir, rel) {
  const abs = path.resolve(outDir, rel);
  const inside = path.relative(outDir, abs);
  if (!inside || inside.startsWith('..') || path.isAbsolute(inside)) return null;
  return abs;
}

async function exists(abs) {
  try {
    return (await stat(abs)).isFile();
  } catch {
    return false;
  }
}

async function transform(rel, bytes, srcDir) {
  const ext = path.posix.extname(rel);
  const out = [rel];
  const files = new Map();
  if (ext === '.js' || ext === '.mjs') {
    const text = bytes.toString('utf8');
    files.set(rel, `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`);
  } else if (ext === '.css') {
    const text = bytes.toString('utf8');
    const names = new Map();
    for (const match of text.matchAll(URL_RE)) {
      const target = match[1];
      const relTarget = resolveDep(rel, target);
      const depBytes = await readFile(path.join(srcDir, relTarget));
      const name = hashedName(relTarget, depBytes);
      const outRel = path.posix.join(path.posix.dirname(rel), name);
      names.set(target, name);
      files.set(outRel, depBytes);
      out.push(outRel);
    }
    files.set(rel, text.replace(URL_RE, (whole, target) => `url(${names.get(target) ?? target})`));
  } else if (ext === '.json') {
    const own = JSON.parse(bytes.toString('utf8'));
    let merged = own;
    if (own && typeof own.extends === 'string') {
      const relBase = resolveDep(rel, own.extends);
      const base = JSON.parse(await readFile(path.join(srcDir, relBase), 'utf8'));
      const { extends: dropped, ...rest } = own;
      merged = { ...base, ...rest };
    }
    files.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
  } else {
    files.set(rel, bytes);
  }
  return { rel, out, files };
}

/**
 * Work out what a build would do, without touching the filesystem outside `src`.
 *
 * A file is rebuilt when any of these hold:
 *   - it has no manifest entry,
 *   - its content fingerprint changed (bytes, never stat metadata),
 *   - a recorded dependency's fingerprint changed (JS imports, CSS `url(...)`,
 *     JSON `extends`),
 *   - an output recorded for it is gone from `out` (self-healing manifest).
 */
export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const { isOwned } = createOwned({ cwd, opts });
  const sources = await walk(srcDir, srcDir, isOwned);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const read = await mapLimit(sources, limit, async (rel) => {
    const bytes = await readFile(path.join(srcDir, rel));
    const ext = path.posix.extname(rel);
    return { rel, bytes, key: fingerprint(bytes), specs: specifiersFor(ext, bytes.toString('utf8')) };
  });

  const keys = new Map(read.map((entry) => [entry.rel, entry.key]));
  const deps = new Map();
  for (const entry of read) {
    const resolved = {};
    for (const spec of entry.specs) {
      const target = resolveDep(entry.rel, spec);
      if (target) resolved[target] = keys.get(target) ?? 'missing';
    }
    deps.set(entry.rel, resolved);
  }

  const prevFiles = manifest.files;
  const stale = new Map();
  for (const entry of read) {
    const prev = prevFiles[entry.rel];
    const recorded = deps.get(entry.rel) ?? {};
    const depChanged = Object.entries(recorded).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const outputsGone =
      !prev?.out || prev.out.length === 0 || !(await mapLimit(prev.out, limit, (name) => exists(outPath(outDir, name) ?? ''))).every(Boolean);
    stale.set(entry.rel, !prev || prev.key !== entry.key || depChanged || outputsGone);
  }

  const dirty = read.filter((entry) => stale.get(entry.rel));
  const built = dirty.map((entry) => entry.rel);
  const skipped = read.filter((entry) => !stale.get(entry.rel)).map((entry) => entry.rel);
  const results = await mapLimit(dirty, limit, (entry) => transform(entry.rel, entry.bytes, srcDir));

  const outputs = new Map();
  for (const result of results) {
    for (const [name, content] of result.files) outputs.set(name, content);
  }

  const nextFiles = {};
  const deletions = new Set();
  for (const entry of read) {
    const fresh = results.find((result) => result.rel === entry.rel);
    const out = fresh ? fresh.out : (prevFiles[entry.rel]?.out ?? [entry.rel]);
    nextFiles[entry.rel] = { key: entry.key, deps: deps.get(entry.rel) ?? {}, out };
    if (fresh) {
      const keep = new Set(out);
      for (const name of prevFiles[entry.rel]?.out ?? []) if (!keep.has(name)) deletions.add(name);
    }
  }

  const removed = Object.keys(prevFiles).filter((rel) => !(rel in nextFiles));
  for (const rel of removed) {
    const recorded = prevFiles[rel].out ?? [rel];
    if (recorded.length === 0) deletions.add(rel);
    for (const name of recorded) deletions.add(name);
  }

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    deletions: [...deletions].filter((name) => !(name in nextFiles) || !outputs.has(name)),
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

/** Remove directories under `root` that a deletion left empty. */
async function pruneEmpty(outDir, dir) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (entry.isDirectory()) await pruneEmpty(outDir, path.join(dir, entry.name));
  }
  if (dir === outDir) return;
  try {
    if ((await readdir(dir)).length === 0) await rmdir(dir);
  } catch {
    /* racing with another writer, or not empty: nothing to do */
  }
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  if (opts.dryRun) {
    return {
      built: plan.built,
      skipped: plan.skipped,
      removed: plan.removed,
      deleted: plan.deletions,
      outputs: plan.outputs.size,
      dryRun: true,
      durationMs: Date.now() - started,
    };
  }
  await mkdir(plan.outDir, { recursive: true });
  await mapLimit([...plan.outputs], limit, async ([rel, content]) => {
    const abs = outPath(plan.outDir, rel);
    if (!abs) return;
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  await mapLimit(plan.deletions, limit, async (rel) => {
    const abs = outPath(plan.outDir, rel);
    if (abs) await rm(abs, { force: true });
  });
  if (plan.deletions.length > 0) await pruneEmpty(plan.outDir, plan.outDir);
  // Outputs are on disk before the manifest claims them, and the manifest write
  // itself is atomic, so an interrupted build never leaves a false record.
  await saveManifest(plan.manifestPath, plan.next);
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    deleted: plan.deletions,
    outputs: plan.outputs.size,
    dryRun: false,
    durationMs: Date.now() - started,
  };
}
