import { mkdir, readdir, readFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { writeAtomic } from './atomic.js';
import { fingerprint } from './cache.js';
import { mapLimit } from './concurrency.js';
import { emit } from './emit.js';
import { MISSING, depsFromText, resolveDep } from './graph.js';
import { emptyManifest, loadManifest, outputsMissing, saveManifest } from './manifest.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 4;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    build at most <n> files at once (default: 4)
  --watch              rebuild whenever a source changes
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --help, -h           show this help
`;

function positiveInt(flag, raw) {
  if (!/^\d+$/.test(String(raw ?? '')) || Number(raw) < 1) {
    throw new Error(`${flag} needs a positive integer`);
  }
  return Number(raw);
}

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
    else if (arg === '--concurrency') opts.concurrency = positiveInt(arg, argv[(index += 1)]);
    else if (arg === '--watch') opts.watch = true;
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

// Symlinks are neither followed nor emitted: a source tree is walked as real files in
// real directories, so a symlink loop can never stall a build.
async function walk(dir, base, exclude) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    // The out dir and the manifest may live inside the source tree; what the build
    // writes is never an input, so those paths are pruned instead of being re-emitted.
    if (exclude.has(abs)) continue;
    if (entry.isDirectory()) files.push(...(await walk(abs, base, exclude)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

// Reads one source and turns it into everything the planner needs: the fingerprint of
// its bytes, and the fingerprint of every source it depends on. Dependencies are
// resolved after the whole tree has been read, so a dependency may appear later in
// the walk order (or not exist at all).
async function scanSource(srcDir, rel) {
  const bytes = await readFile(path.join(srcDir, rel));
  const ext = path.posix.extname(rel).toLowerCase();
  const deps = {};
  for (const spec of depsFromText(bytes.toString('utf8'), ext)) {
    const target = resolveDep(rel, spec);
    if (target && !(target in deps)) deps[target] = MISSING;
  }
  return { rel, bytes, key: fingerprint(bytes), deps };
}

function isDirty(entry, prev, deps, outDir) {
  if (!prev) return true;
  if (prev.key !== entry.key) return true;
  const recorded = prev.deps ?? {};
  for (const [dep, key] of Object.entries(deps)) {
    if (recorded[dep] !== key) return true;
  }
  return outputsMissing(prev, outDir);
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;

  const sources = await walk(srcDir, srcDir, new Set([outDir, manifestPath]));
  const manifest = (await loadManifest(manifestPath)) ?? emptyManifest();

  const scanned = await mapLimit(sources, limit, (rel) => scanSource(srcDir, rel));
  const keys = new Map(scanned.map((entry) => [entry.rel, entry.key]));
  for (const entry of scanned) {
    for (const dep of Object.keys(entry.deps)) entry.deps[dep] = keys.get(dep) ?? MISSING;
  }

  const decisions = await mapLimit(scanned, limit, async (entry) => {
    const prev = manifest.files[entry.rel] ?? null;
    const dirty = await isDirty(entry, prev, entry.deps, outDir);
    return { entry, prev, dirty };
  });

  const stale = [];
  const built = [];
  const skipped = [];
  const emitted = await mapLimit(
    decisions.filter((decision) => decision.dirty),
    limit,
    async ({ entry, prev }) => {
      const result = await emit(entry.rel, { srcDir, deps: entry.deps, bytes: entry.bytes });
      // An output this source produced last time but not this time belongs to no one
      // now, so it is dropped: an incremental build has to leave the same tree a full
      // build would.
      for (const rel of prev?.out ?? []) {
        if (!result.out.includes(rel)) stale.push(rel);
      }
      return { ...entry, out: result.out, files: result.files };
    },
  );

  const outputs = new Map();
  const owned = new Set();
  const nextFiles = {};
  const byRel = new Map();
  for (const item of emitted) {
    built.push(item.rel);
    byRel.set(item.rel, item);
    for (const [rel, content] of item.files) {
      outputs.set(rel, content);
      owned.add(rel);
    }
    nextFiles[item.rel] = { key: item.key, deps: item.deps, out: item.out };
  }
  for (const { entry, prev } of decisions) {
    if (prev && !built.includes(entry.rel)) {
      skipped.push(entry.rel);
      nextFiles[entry.rel] = { key: entry.key, deps: entry.deps, out: prev.out ?? [entry.rel] };
      // A skipped source still owns the outputs it emitted last time: two sources can
      // point at one asset, and a rebuild of the other one must not delete it.
      for (const rel of nextFiles[entry.rel].out) owned.add(rel);
    }
  }

  // A source that is gone takes its manifest entry and its outputs with it.
  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  for (const rel of removed) {
    for (const out of manifest.files[rel]?.out ?? []) stale.push(out);
  }

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    limit,
    outputs,
    stale: [...new Set(stale)].filter((rel) => !owned.has(rel)).sort(),
    removed: removed.sort(),
    built: built.sort(),
    skipped: skipped.sort(),
    next: { version: 2, files: nextFiles },
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
  if (opts.dryRun) return { ...report, durationMs: Date.now() - started };

  await mkdir(plan.outDir, { recursive: true });
  // Outputs land before the manifest records them, so an interrupted build can only
  // ever leave outputs without a manifest entry (rebuilt next run), never an entry
  // pointing at bytes that were never written.
  await mapLimit([...plan.outputs], plan.limit, ([rel, content]) =>
    writeAtomic(path.join(plan.outDir, rel), content),
  );
  await mapLimit(plan.stale, plan.limit, (rel) => rm(path.join(plan.outDir, rel), { force: true }));
  await saveManifest(plan.manifestPath, plan.next);
  return { ...report, durationMs: Date.now() - started };
}

// One build result has one rendering, shared by the CLI and watch mode so both print
// the same bytes for the same report.
export function formatReport(report, json = false) {
  if (json) return `${JSON.stringify(report)}\n`;
  return `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`;
}
