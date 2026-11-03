import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { readDeps } from './graph.js';
import { cacheKey, shortHash } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { walk, anyMissing, writeAtomic, removeFile } from './fsutil.js';
import { mapLimit } from './limit.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';

// File reads and writes are independent per path; a small pool keeps the syscall
// count bounded without serializing the whole build.
const CONCURRENCY = 16;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>        source directory (default: src)
  --out <dir>        output directory (default: out)
  --manifest <file>  build manifest path (default: build-manifest.json)
  --dry-run          report the plan without writing anything
  --watch            rebuild whenever the source tree changes
  --concurrency <n>  maximum parallel file operations (default: 16)
  --json             print a machine-readable report
  --help, -h         show this help
`;

function positiveInt(raw, flag) {
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error(`${flag} needs a positive integer, got: ${raw}`);
  }
  return parsed;
}

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: CONCURRENCY,
    dryRun: false,
    watch: false,
    json: false,
    help: false,
  };
  const value = (index, flag) => {
    const next = argv[index];
    if (next === undefined || next.startsWith('--')) throw new Error(`${flag} needs a value`);
    return next;
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = value((index += 1), '--src');
    else if (arg === '--out') opts.out = value((index += 1), '--out');
    else if (arg === '--manifest') opts.manifest = value((index += 1), '--manifest');
    else if (arg === '--concurrency') {
      opts.concurrency = positiveInt(value((index += 1), '--concurrency'), '--concurrency');
    } else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  return opts;
}

// A dependency specifier is either a relative path inside the source tree or
// something the build cannot own (absolute paths, URLs, bare package names).
function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, data) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${shortHash(data)}${ext}`;
}

const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir);
  const sourceSet = new Set(sources);
  const loaded = await loadManifest(manifestPath);
  const manifest = loaded ?? { version: MANIFEST_VERSION, files: {} };

  const bytes = new Map();
  const ownKeys = new Map();
  await mapLimit(sources, opts.concurrency ?? CONCURRENCY, async (rel) => {
    const data = await readFile(path.join(srcDir, rel));
    bytes.set(rel, data);
    ownKeys.set(rel, cacheKey(data));
  });

  const texts = new Map();
  const text = (rel) => {
    if (!texts.has(rel)) texts.set(rel, bytes.has(rel) ? bytes.get(rel).toString('utf8') : '');
    return texts.get(rel);
  };

  const deps = new Map();
  for (const rel of sources) {
    const resolved = new Set();
    for (const spec of readDeps(text(rel), path.posix.extname(rel))) {
      const target = resolveDep(rel, spec);
      if (target && target !== rel) resolved.add(target);
    }
    deps.set(rel, [...resolved].sort());
  }

  // A dependency fingerprint is the dependency's *effective* fingerprint: its own
  // bytes plus everything it depends on. That way a change two edges away (json
  // extends a chain, a stylesheet importing an asset another stylesheet hashes)
  // still rebuilds the referrer, and a full rebuild and an incremental one agree.
  const effective = new Map();
  const visiting = new Set();
  const effectiveKey = (rel) => {
    if (!ownKeys.has(rel)) return 'missing';
    if (effective.has(rel)) return effective.get(rel);
    if (visiting.has(rel)) return ownKeys.get(rel);
    visiting.add(rel);
    const parts = (deps.get(rel) ?? [])
      .map((dep) => `${dep}\u0000${effectiveKey(dep)}`)
      .sort();
    const value = cacheKey(`${ownKeys.get(rel)}\n${parts.join('\n')}`);
    visiting.delete(rel);
    effective.set(rel, value);
    return value;
  };

  const mergedJson = (rel, seen = new Set()) => {
    const parsed = JSON.parse(text(rel));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return parsed;
    const { extends: spec, ...rest } = parsed;
    if (typeof spec !== 'string') return rest;
    const baseRel = resolveDep(rel, spec);
    if (!baseRel || !sourceSet.has(baseRel) || seen.has(rel)) return rest;
    const base = mergedJson(baseRel, new Set(seen).add(rel));
    if (!base || typeof base !== 'object' || Array.isArray(base)) return rest;
    return { ...base, ...rest };
  };

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  const emit = (rel) => {
    const ext = path.posix.extname(rel);
    const data = bytes.get(rel);
    if (ext === '.js' || ext === '.mjs') {
      const source = text(rel);
      outputs.set(rel, `${source.trimEnd()}\n//# build ${shortHash(source)}\n`);
      return [rel];
    }
    if (ext === '.css') {
      const names = new Map();
      const assets = [];
      for (const spec of readDeps(text(rel), '.css')) {
        if (names.has(spec)) continue;
        const target = resolveDep(rel, spec);
        if (!target || !sourceSet.has(target)) continue;
        const name = hashedName(target, bytes.get(target));
        const outRel = path.posix.join(path.posix.dirname(rel), name);
        names.set(spec, name);
        if (!outputs.has(outRel)) outputs.set(outRel, bytes.get(target));
        assets.push(outRel);
      }
      const source = text(rel);
      outputs.set(
        rel,
        source.replace(URL_RE, (whole, target) => (names.has(target) ? `url(${names.get(target)})` : whole)),
      );
      return [rel, ...assets];
    }
    if (ext === '.json') {
      outputs.set(rel, `${JSON.stringify(mergedJson(rel), null, 2)}\n`);
      return [rel];
    }
    outputs.set(rel, data);
    return [rel];
  };

  for (const rel of sources) {
    const key = ownKeys.get(rel);
    const depKeys = {};
    for (const dep of deps.get(rel) ?? []) depKeys[dep] = effectiveKey(dep);
    const prev = manifest.files[rel];
    const prevDeps = prev?.deps ?? {};
    const depChanged =
      Object.keys(depKeys).some((dep) => prevDeps[dep] !== depKeys[dep]) ||
      Object.keys(prevDeps).some((dep) => !(dep in depKeys));
    const prevOut = Array.isArray(prev?.out) ? prev.out : null;
    const outputsOk = prevOut !== null && !(await anyMissing(outDir, prevOut));
    if (prev && prev.key === key && !depChanged && outputsOk) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: depKeys, out: prevOut };
      continue;
    }
    built.push(rel);
    nextFiles[rel] = { key, deps: depKeys, out: emit(rel) };
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));

  // Outputs that the previous run recorded but this run no longer produces: a
  // renamed hashed asset, or every output of a deleted source. They must go, or
  // an incremental tree would carry files a full rebuild would not create.
  const kept = new Set();
  for (const entry of Object.values(nextFiles)) for (const out of entry.out) kept.add(out);
  const stale = [];
  const staleSeen = new Set();
  for (const rel of [...built, ...removed]) {
    for (const out of manifest.files[rel]?.out ?? []) {
      if (kept.has(out) || staleSeen.has(out)) continue;
      staleSeen.add(out);
      stale.push(out);
    }
  }

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    stale,
    removed,
    built,
    skipped,
    previous: manifest,
    hadManifest: loaded !== null,
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
  for (const rel of plan.stale) await removeFile(path.join(plan.outDir, rel));
  await mkdir(plan.outDir, { recursive: true });
  await mapLimit([...plan.outputs], opts.concurrency ?? CONCURRENCY, ([rel, content]) =>
    writeAtomic(path.join(plan.outDir, rel), content),
  );
  const unchanged = plan.hadManifest && JSON.stringify(plan.previous) === JSON.stringify(plan.next);
  if (!unchanged) await saveManifest(plan.manifestPath, plan.next);
  report.durationMs = Date.now() - started;
  return report;
}
