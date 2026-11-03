import { readdir, readFile, stat, mkdir, writeFile, rm, rmdir } from 'node:fs/promises';
import path from 'node:path';
import { depsFromText } from './graph.js';
import { fingerprint, shortHash } from './cache.js';
import { resolveSourcePath } from './paths.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 8;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    build at most n files at once (default: ${DEFAULT_CONCURRENCY})
  --watch, -w          rebuild whenever a source file changes
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
    else if (arg === '--concurrency') opts.concurrency = argv[(index += 1)];
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--watch' || arg === '-w') opts.watch = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  const limit = Number(opts.concurrency);
  if (!Number.isInteger(limit) || limit < 1) {
    throw new Error('--concurrency needs a positive integer');
  }
  opts.concurrency = limit;
  return opts;
}

export async function walk(dir, base = dir) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch (error) {
    if (error && error.code === 'ENOENT') return [];
    throw error;
  }
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, async () => {
    while (next < items.length) {
      const index = next;
      next += 1;
      results[index] = await fn(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${shortHash(bytes)}${ext}`;
}

function urlPattern() {
  return /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

async function exists(file) {
  try {
    return (await stat(file)).isFile();
  } catch {
    return false;
  }
}

/**
 * Merge a JSON file with the bases it pulls in through `extends`.
 *
 * The base object is merged first and the own keys override it; the chain is
 * followed so a change anywhere along it still contributes to the output.
 */
function mergeJson(rel, textOf, sources, seen = new Set()) {
  const own = JSON.parse(textOf(rel));
  if (!isPlainObject(own) || typeof own.extends !== 'string') return own;
  const { extends: spec, ...rest } = own;
  const base = resolveSourcePath(rel, spec);
  if (!base || !sources.has(base) || seen.has(base)) return rest;
  const nextSeen = new Set(seen);
  nextSeen.add(base);
  const merged = mergeJson(base, textOf, sources, nextSeen);
  return { ...(isPlainObject(merged) ? merged : {}), ...rest };
}

/** Every base file a JSON source pulls in, transitively, in reference order. */
function jsonChain(rel, textOf, sources) {
  const chain = [];
  const seen = new Set([rel]);
  let current = rel;
  while (true) {
    let spec;
    try {
      spec = depsFromText(textOf(current), '.json')[0];
    } catch {
      return chain;
    }
    if (typeof spec !== 'string') return chain;
    const base = resolveSourcePath(current, spec);
    if (!base || !sources.has(base) || seen.has(base)) return chain;
    chain.push(base);
    seen.add(base);
    current = base;
  }
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = Number.isInteger(opts.concurrency) && opts.concurrency > 0 ? opts.concurrency : DEFAULT_CONCURRENCY;

  const sources = await walk(srcDir);
  const sourceSet = new Set(sources);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };
  const previous = isPlainObject(manifest.files) ? manifest.files : {};

  // Every fingerprint is taken from the bytes, never from file metadata.
  const bytes = new Map();
  await mapLimit(sources, limit, async (rel) => {
    bytes.set(rel, await readFile(path.join(srcDir, rel)));
  });
  const keys = new Map();
  for (const rel of sources) keys.set(rel, fingerprint(bytes.get(rel)));
  const textOf = (rel) => bytes.get(rel).toString('utf8');

  // Reference edges, resolved once so a change in a referenced file invalidates
  // the referrer.
  const deps = new Map();
  await mapLimit(sources, limit, async (rel) => {
    const ext = path.posix.extname(rel);
    const resolved = {};
    for (const spec of depsFromText(textOf(rel), ext)) {
      const target = resolveSourcePath(rel, spec);
      if (target) resolved[target] = null;
    }
    if (ext === '.json') {
      for (const base of jsonChain(rel, textOf, sourceSet)) resolved[base] = null;
    }
    deps.set(rel, resolved);
  });
  for (const resolved of deps.values()) {
    for (const target of Object.keys(resolved)) {
      resolved[target] = keys.get(target) ?? 'missing';
    }
  }

  // An output that vanished from disk has to be produced again, even when the
  // manifest still records an unchanged source.
  const intact = new Map();
  await mapLimit(sources, limit, async (rel) => {
    const recorded = previous[rel]?.out ?? [rel];
    for (const name of recorded) {
      if (!(await exists(path.join(outDir, name)))) {
        intact.set(rel, false);
        return;
      }
    }
    intact.set(rel, true);
  });

  const results = await mapLimit(sources, limit, async (rel) => {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = previous[rel];
    const prevOut = prev?.out ?? [rel];
    const prevDeps = isPlainObject(prev?.deps) ? prev.deps : {};
    const depChanged = Object.entries(resolved).some(([dep, depKey]) => prevDeps[dep] !== depKey)
      || Object.keys(prevDeps).length !== Object.keys(resolved).length;
    const dirty = !prev || prev.key !== key || depChanged || intact.get(rel) === false;
    if (!dirty) return { rel, dirty: false, outNames: prevOut, entries: [], prevOut };

    const ext = path.posix.extname(rel);
    const entries = [];
    let outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      const text = textOf(rel);
      entries.push([rel, `${text.trimEnd()}\n//# build ${shortHash(text)}\n`]);
    } else if (ext === '.css') {
      const text = textOf(rel);
      const dir = path.posix.dirname(rel);
      const names = new Map();
      for (const match of text.matchAll(urlPattern())) {
        const target = match[1];
        if (names.has(target)) continue;
        // A fragment or query selects something inside the target, not another file.
        const bare = target.replace(/[?#].*$/, '');
        const relTarget = bare === '' ? null : resolveSourcePath(rel, bare);
        if (!relTarget || !sourceSet.has(relTarget)) continue;
        const name = hashedName(relTarget, bytes.get(relTarget));
        names.set(target, name);
        entries.push([path.posix.join(dir === '.' ? '' : dir, name), bytes.get(relTarget)]);
      }
      entries.push([rel, text.replace(urlPattern(), (whole, target) => `url(${names.get(target) ?? target})`)]);
      outNames = [rel, ...names.values()];
    } else if (ext === '.json') {
      entries.push([rel, `${JSON.stringify(mergeJson(rel, textOf, sourceSet), null, 2)}\n`]);
    } else {
      entries.push([rel, bytes.get(rel)]);
    }
    return { rel, dirty: true, outNames, entries, prevOut };
  });

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};
  const stale = new Set();

  for (const result of results) {
    const rel = result.rel;
    if (!result.dirty) {
      skipped.push(rel);
    } else {
      built.push(rel);
      for (const [name, content] of result.entries) outputs.set(name, content);
      for (const name of result.prevOut) {
        if (!result.outNames.includes(name)) stale.add(name);
      }
    }
    nextFiles[rel] = { key: keys.get(rel), deps: deps.get(rel) ?? {}, out: result.outNames };
  }

  const removed = Object.keys(previous).filter((rel) => !(rel in nextFiles));
  for (const rel of removed) {
    for (const name of previous[rel]?.out ?? [rel]) stale.add(name);
  }
  // Never delete a path that this build produces or still tracks.
  for (const name of outputs.keys()) stale.delete(name);
  for (const entry of Object.values(nextFiles)) {
    for (const name of entry.out) stale.delete(name);
  }

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    staleOutputs: [...stale].sort(),
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

/** Best-effort removal of directories a deleted output leaves empty. */
async function pruneEmptyDirs(dir, stopAt) {
  let current = dir;
  while (current !== stopAt && current.startsWith(stopAt)) {
    try {
      await rmdir(current);
    } catch {
      return;
    }
    current = path.dirname(current);
  }
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
    durationMs: Date.now() - started,
  };
  if (opts.dryRun) return report;

  await mkdir(plan.outDir, { recursive: true });
  for (const name of plan.staleOutputs) {
    const abs = path.join(plan.outDir, name);
    await rm(abs, { force: true });
    await pruneEmptyDirs(path.dirname(abs), plan.outDir);
  }
  for (const [rel, content] of plan.outputs) {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  // The manifest is the commit record: written last, and atomically.
  await saveManifest(plan.manifestPath, plan.next);
  return report;
}

/** One-line summary of a report, shared by the CLI and watch mode. */
export function formatReport(report) {
  const verb = report.dryRun ? 'planned' : 'built';
  return `${verb} ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`;
}
