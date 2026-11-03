import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { cacheKey } from './cache.js';
import { URL_RE, readDeps } from './graph.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { listOutputs, removeOutputs, staleOutputs } from './outputs.js';
import { mapLimit } from './pool.js';
import { readTree } from './tree.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 1;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>        source directory (default: src)
  --out <dir>        output directory (default: out)
  --manifest <file>  build manifest path (default: build-manifest.json)
  --concurrency <n>  build at most <n> files at once (default: 1)
  --watch            rebuild whenever a source file changes
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
    dryRun: false,
    watch: false,
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
      if (!/^[1-9]\d*$/.test(value ?? '')) throw new Error('--concurrency needs a positive integer');
      opts.concurrency = Number(value);
    } else if (arg === '--watch') opts.watch = true;
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  if (opts.watch && opts.dryRun) throw new Error('--watch cannot be combined with --dry-run');
  return opts;
}

function resolveDep(rel, spec) {
  if (spec.startsWith('#')) return null;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${cacheKey(bytes).slice(0, 8)}${ext}`;
}

function relativeInside(parent, child) {
  const rel = path.relative(parent, child);
  if (rel === '') return '';
  if (rel.startsWith('..') || path.isAbsolute(rel)) return null;
  return rel.split(path.sep).join('/');
}

function depsChanged(prev, next) {
  const keys = Object.keys(next);
  if (keys.length !== Object.keys(prev).length) return true;
  return keys.some((dep) => prev[dep] !== next[dep]);
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const concurrency = opts.concurrency ?? DEFAULT_CONCURRENCY;

  const sources = await readTree(srcDir, { concurrency });
  const keys = new Map();
  for (const [rel, bytes] of sources) keys.set(rel, cacheKey(bytes));

  // Dependencies are resolved after every fingerprint is known so that a file
  // referring to one that sorts after it is not recorded as 'missing'.
  const deps = new Map();
  for (const [rel, bytes] of sources) {
    const resolved = {};
    for (const spec of readDeps(bytes, path.posix.extname(rel))) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = keys.get(target) ?? 'missing';
    }
    deps.set(rel, resolved);
  }

  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };
  const present = await listOutputs(outDir);

  const dirty = new Set();
  for (const rel of sources.keys()) {
    const prev = manifest.files[rel];
    const resolved = deps.get(rel);
    if (!prev) dirty.add(rel);
    else if (prev.key !== keys.get(rel)) dirty.add(rel);
    else if (depsChanged(prev.deps, resolved)) dirty.add(rel);
    else if (prev.out.length === 0) dirty.add(rel);
    else if (prev.out.some((name) => !present.has(name))) dirty.add(rel);
  }

  const assetCache = new Map();
  const readAsset = async (rel) => {
    if (sources.has(rel)) return sources.get(rel);
    if (assetCache.has(rel)) return assetCache.get(rel);
    const bytes = await readFile(path.join(srcDir, rel));
    assetCache.set(rel, bytes);
    return bytes;
  };

  const render = async (rel) => {
    const bytes = sources.get(rel);
    const ext = path.posix.extname(rel);
    const files = new Map();
    const outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      const text = bytes.toString('utf8');
      files.set(rel, `${text.trimEnd()}\n//# build ${cacheKey(bytes).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = bytes.toString('utf8');
      const names = new Map();
      for (const match of text.matchAll(URL_RE)) {
        const target = match[1];
        if (names.has(target)) continue;
        const relTarget = resolveDep(rel, target);
        if (!relTarget) continue;
        const asset = await readAsset(relTarget);
        const name = hashedName(relTarget, asset);
        names.set(target, name);
        files.set(name, asset);
        if (!outNames.includes(name)) outNames.push(name);
      }
      files.set(rel, text.replace(URL_RE, (whole, target) => `url(${names.get(target) ?? target})`));
    } else if (ext === '.json') {
      const own = JSON.parse(bytes.toString('utf8'));
      let merged = own;
      if (own && typeof own.extends === 'string') {
        const relBase = resolveDep(rel, own.extends);
        if (relBase) {
          const base = JSON.parse((await readAsset(relBase)).toString('utf8'));
          const { extends: dropped, ...rest } = own;
          merged = { ...base, ...rest };
        }
      }
      files.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
    } else {
      files.set(rel, bytes);
    }
    return { outNames, files };
  };

  const rendered = new Map();
  await mapLimit(
    sources.keys().filter((rel) => dirty.has(rel)),
    concurrency,
    async (rel) => rendered.set(rel, await render(rel)),
  );

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};
  for (const rel of sources.keys()) {
    const resolved = deps.get(rel);
    if (dirty.has(rel)) {
      const result = rendered.get(rel);
      built.push(rel);
      for (const [name, content] of result.files) outputs.set(name, content);
      nextFiles[rel] = { key: keys.get(rel), deps: resolved, out: result.outNames };
    } else {
      skipped.push(rel);
      nextFiles[rel] = { key: keys.get(rel), deps: resolved, out: manifest.files[rel].out };
    }
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));

  // Anything in the output directory that no source claims is either an output
  // of a deleted source, a stale hashed asset, or debris from an interrupted
  // build. Skipped when the source tree lives inside the output directory,
  // because then the output directory is not exclusively ours.
  const claimed = new Set();
  for (const [rel, entry] of Object.entries(nextFiles)) {
    claimed.add(rel);
    for (const name of entry.out) claimed.add(name);
  }
  const manifestRel = relativeInside(outDir, manifestPath);
  if (manifestRel) claimed.add(manifestRel);
  const prune = relativeInside(outDir, srcDir) === null ? staleOutputs(present, claimed) : [];

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    prune,
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const concurrency = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) {
    return {
      built: plan.built,
      skipped: plan.skipped,
      removed: plan.removed,
      pruned: plan.prune.length,
      outputs: plan.outputs.size,
      dryRun: true,
      durationMs: Date.now() - started,
    };
  }
  await mkdir(plan.outDir, { recursive: true });
  await mapLimit([...plan.outputs], concurrency, async ([rel, content]) => {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  const pruned = await removeOutputs(plan.outDir, plan.prune, { concurrency });
  // The manifest is written last and atomically: if the build dies before this
  // point the previous manifest is still intact and the next build redoes the
  // work instead of trusting a manifest that describes files it never wrote.
  await saveManifest(plan.manifestPath, plan.next);
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    pruned,
    outputs: plan.outputs.size,
    dryRun: false,
    durationMs: Date.now() - started,
  };
}
