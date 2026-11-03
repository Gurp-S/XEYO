import { stat } from 'node:fs/promises';
import { availableParallelism } from 'node:os';
import path from 'node:path';
import { writeFileAtomic } from './atomic.js';
import { cacheKey } from './cache.js';
import { emitSource, resolveDep } from './emit.js';
import { readDeps } from './graph.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { mapPool } from './pool.js';
import { pruneOutputs } from './prune.js';
import { walk } from './walk.js';
import { watchSources } from './watch.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = availableParallelism();

/** Fingerprint stand-in for a dependency that is not a file of this tree. */
const MISSING_DEP = 'missing';

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --watch              rebuild whenever the source tree changes
  --concurrency <n>    build at most n files at once (default: ${DEFAULT_CONCURRENCY})
  --help, -h           show this help
`;

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    dryRun: false,
    json: false,
    watch: false,
    concurrency: DEFAULT_CONCURRENCY,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
    else if (arg === '--concurrency') opts.concurrency = parseConcurrency(argv[(index += 1)]);
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  return opts;
}

function parseConcurrency(value) {
  if (value === undefined) throw new Error('--concurrency needs a value');
  const limit = Number(value);
  if (!Number.isInteger(limit) || limit < 1) throw new Error(`--concurrency needs a positive integer, got: ${value}`);
  return limit;
}

function sameDeps(recorded, current) {
  const recordedKeys = Object.keys(recorded ?? {});
  if (recordedKeys.length !== Object.keys(current ?? {}).length) return false;
  return recordedKeys.every((key) => Object.prototype.hasOwnProperty.call(current, key) && recorded[key] === current[key]);
}

/** True when every output the manifest claims for a source is actually on disk. */
async function outputsPresent(outDir, outputs) {
  if (!Array.isArray(outputs) || outputs.length === 0) return false;
  for (const rel of outputs) {
    try {
      if (!(await stat(path.join(outDir, rel))).isFile()) return false;
    } catch {
      return false;
    }
  }
  return true;
}

/**
 * Work out what a build would do without touching the filesystem beyond
 * reading sources: which sources are stale, the bytes each stale source
 * produces, which outputs have become orphans, and the manifest that describes
 * the result.
 */
export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const ignore = new Set([outDir, manifestPath]);

  const sources = await walk(srcDir, srcDir, (abs) => ignore.has(abs));
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const keys = new Map(await mapPool(sources, limit, async (rel) => [rel, await cacheKey(path.join(srcDir, rel))]));

  const deps = new Map(
    await mapPool(sources, limit, async (rel) => {
      const recorded = {};
      for (const spec of await readDeps(path.join(srcDir, rel), path.posix.extname(rel))) {
        const target = resolveDep(rel, spec);
        if (target) recorded[target] = keys.get(target) ?? MISSING_DEP;
      }
      return [rel, recorded];
    }),
  );

  const fresh = await mapPool(sources, limit, async (rel) => {
    const previous = manifest.files[rel];
    if (!previous) return false;
    if (previous.key !== keys.get(rel)) return false;
    if (!sameDeps(previous.deps, deps.get(rel))) return false;
    return outputsPresent(outDir, previous.out);
  });

  const dirty = sources.filter((_, index) => !fresh[index]);
  const emitted = new Map();
  const built = await mapPool(dirty, limit, async (rel) => {
    const pairs = await emitSource(srcDir, rel);
    emitted.set(rel, pairs);
    return rel;
  });

  const outputs = [];
  const nextFiles = {};
  for (const rel of sources) {
    const pairs = emitted.get(rel);
    if (pairs) {
      for (const [outRel, content] of pairs) outputs.push([outRel, content]);
      nextFiles[rel] = { key: keys.get(rel), deps: deps.get(rel), out: pairs.map(([outRel]) => outRel) };
    } else {
      nextFiles[rel] = { key: keys.get(rel), deps: deps.get(rel), out: manifest.files[rel].out };
    }
  }

  const pruned = new Set();
  for (const [rel, entry] of Object.entries(manifest.files)) {
    const keep = new Set(nextFiles[rel]?.out ?? []);
    for (const out of entry.out ?? []) if (!keep.has(out)) pruned.add(out);
  }
  const produced = new Set(Object.values(nextFiles).flatMap((entry) => entry.out));
  for (const out of [...pruned]) if (produced.has(out)) pruned.delete(out);

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    pruned: [...pruned].sort(),
    built,
    skipped: sources.filter((_, index) => fresh[index]),
    removed: Object.keys(manifest.files).filter((rel) => !(rel in nextFiles)).sort(),
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

function report(plan, dryRun, started) {
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.length,
    pruned: plan.pruned,
    dryRun,
    durationMs: Date.now() - started,
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) return report(plan, true, started);
  for (const [rel, content] of plan.outputs) await writeFileAtomic(path.join(plan.outDir, rel), content);
  await pruneOutputs(plan.outDir, plan.pruned);
  await saveManifest(plan.manifestPath, plan.next);
  return report(plan, false, started);
}

/**
 * Build once, then keep building whenever the bytes of the source tree change.
 * Resolves when `signal` aborts.
 */
export async function runWatch(opts, cwd = process.cwd(), { signal, onReport, onError } = {}) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const cycle = async () => onReport?.(await build(opts, cwd));
  await cycle();
  await watchSources({
    srcDir,
    outDir,
    concurrency: opts.concurrency ?? DEFAULT_CONCURRENCY,
    signal,
    onChange: cycle,
    onError,
  });
}
