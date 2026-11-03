import { readdir, readFile, mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { readDeps } from './graph.js';
import { fingerprint } from './cache.js';
import { emit } from './emit.js';
import { resolveDep } from './paths.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>        source directory (default: src)
  --out <dir>        output directory (default: out)
  --manifest <file>  build manifest path (default: build-manifest.json)
  --dry-run          report the plan without writing anything
  --json             print a machine-readable report
  --help, -h         show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    dryRun: false,
    json: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
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

async function walk(dir, base) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (err) {
    if (err.code === 'ENOENT' && dir === base) return [];
    throw err;
  }
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  // Source bytes are read once: the fingerprint derives from them, and the same
  // map backs the synchronous dependency lookup used while emitting.
  const bytes = new Map();
  const keys = new Map();
  const deps = new Map();
  for (const rel of sources) {
    const abs = path.join(srcDir, rel);
    const content = await readFile(abs);
    bytes.set(rel, content);
    keys.set(rel, fingerprint(content));
    const specifiers = await readDeps(abs, path.posix.extname(rel));
    const resolved = {};
    for (const spec of specifiers) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = null;
    }
    deps.set(rel, resolved);
  }
  for (const resolved of deps.values()) {
    for (const target of Object.keys(resolved)) resolved[target] = keys.get(target) ?? 'missing';
  }

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of sources) {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const dirty = !prev || prev.key !== key || stale;
    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out ?? [rel] };
      continue;
    }
    built.push(rel);
    const rendered = await emit(rel, bytes.get(rel), (target) => bytes.get(target));
    for (const file of rendered.files) outputs.set(file.name, file.bytes);
    nextFiles[rel] = { key, deps: resolved, out: rendered.out };
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  // Outputs the previous manifest produced that this run no longer produces:
  // files of deleted sources and hashed assets superseded by a rebuild. Files
  // of skipped sources are left alone, and an output still produced by any
  // source (a shared asset) is never dropped.
  const stale = new Set();
  for (const [rel, meta] of Object.entries(manifest.files)) {
    const keep = new Set(nextFiles[rel]?.out ?? []);
    for (const name of meta.out ?? []) if (!keep.has(name) && !outputs.has(name)) stale.add(name);
  }
  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    removed,
    stale: [...stale],
    built,
    skipped,
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
  await saveManifest(plan.manifestPath, plan.next);
  for (const rel of plan.stale) {
    await rm(path.join(plan.outDir, rel), { force: true });
  }
  for (const [rel, content] of plan.outputs) {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun: false,
    durationMs: Date.now() - started,
  };
}
