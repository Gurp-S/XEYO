import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { availableParallelism } from 'node:os';
import { readDeps, resolveDep } from './deps.js';
import { fingerprintFile } from './fingerprint.js';
import { renderSource } from './render.js';
import { missingOutputs, removeOutputs } from './prune.js';
import { writeAtomic } from './write.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';

export function defaultConcurrency() {
  const cpus = typeof availableParallelism === 'function' ? availableParallelism() : 4;
  return Math.max(1, Math.min(8, cpus));
}

// Bounded worker pool: runs `worker` over `items`, at most `limit` at a time,
// and returns the results in the original item order.
export async function mapLimit(items, limit, worker) {
  const results = new Array(items.length);
  let next = 0;
  const size = Math.max(1, Math.min(limit, items.length));
  const runners = Array.from({ length: size }, async () => {
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

// Source paths are collected in sorted order so every downstream step is
// deterministic. Symbolic links are neither files nor directories here, so
// they are ignored, exactly as before.
export async function walk(dir, base) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

export async function collectSources(srcDir, concurrency) {
  const sources = await walk(srcDir, srcDir);
  const fingerprints = await mapLimit(sources, concurrency, (rel) =>
    fingerprintFile(path.join(srcDir, rel)),
  );
  const keys = new Map();
  sources.forEach((rel, index) => keys.set(rel, fingerprints[index]));

  const deps = new Map();
  await mapLimit(sources, concurrency, async (rel) => {
    const abs = path.join(srcDir, rel);
    const resolved = {};
    for (const spec of await readDeps(abs, path.posix.extname(rel))) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = null;
    }
    deps.set(rel, resolved);
  });
  // Dependencies are compared by fingerprint, so a missing target is recorded
  // as "missing" and starts matching once the asset appears.
  for (const resolved of deps.values()) {
    for (const target of Object.keys(resolved)) resolved[target] = keys.get(target) ?? 'missing';
  }
  return { sources, keys, deps };
}

export async function planBuild(opts, cwd = process.cwd(), concurrency = opts.concurrency) {
  const limit = concurrency ?? defaultConcurrency();
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };
  const { sources, keys, deps } = await collectSources(srcDir, limit);

  const built = [];
  const skipped = [];
  const nextFiles = {};
  const dirty = [];

  for (const rel of sources) {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    // A manifest entry whose outputs vanished must be rebuilt, not skipped.
    const broken = prev?.out ? await missingOutputs(outDir, prev.out) : false;
    if (prev && prev.key === key && !stale && !broken) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out ?? [rel] };
      continue;
    }
    built.push(rel);
    dirty.push(rel);
    nextFiles[rel] = { key, deps: resolved, out: [] };
  }

  const rendered = await mapLimit(dirty, limit, async (rel) => {
    const result = await renderSource({ abs: path.join(srcDir, rel), rel, srcDir });
    return { rel, result };
  });

  const outputs = new Map();
  for (const { rel, result } of rendered) {
    outputs.set(rel, result.content);
    const outs = [rel];
    for (const [assetRel, bytes] of result.assets) {
      outputs.set(assetRel, bytes);
      outs.push(assetRel);
    }
    nextFiles[rel].out = outs;
  }

  // Outputs a rebuilt file no longer claims (a renamed content-hashed asset).
  const pruned = [];
  for (const rel of built) {
    const prev = manifest.files[rel];
    if (!prev?.out) continue;
    const keep = new Set(nextFiles[rel].out);
    for (const out of prev.out) if (!keep.has(out)) pruned.push(out);
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  for (const rel of removed) pruned.push(...(manifest.files[rel].out ?? [rel]));

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    pruned: [...new Set(pruned)],
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd(), concurrency = opts.concurrency) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd, concurrency);
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
  // Stale outputs go first: an interrupted build then leaves at worst a
  // missing file, never a stale one.
  await removeOutputs(plan.outDir, plan.pruned);
  // Outputs are written in sorted path order, so the write sequence does not
  // depend on the concurrency limit.
  for (const rel of [...plan.outputs.keys()].sort()) {
    await writeAtomic(path.join(plan.outDir, rel), plan.outputs.get(rel));
  }
  // The manifest is written last and atomically, so it only ever describes
  // outputs that already exist.
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
