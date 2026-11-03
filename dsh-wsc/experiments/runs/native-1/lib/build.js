import { mkdir, readdir, readFile, rmdir, stat, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { depsFromText, urlRe } from './graph.js';
import { cacheKey, sha1Hex } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { mapLimit } from './pool.js';

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
  --concurrency <n>    max files built at once (default: 8)
  --watch              rebuild whenever a source changes
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --help, -h           show this help
`;

/** Flags that consume the following argument as their value. */
const VALUE_FLAGS = new Set(['--src', '--out', '--manifest', '--concurrency']);

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
    if (VALUE_FLAGS.has(arg)) {
      const value = argv[(index += 1)];
      if (value === undefined || value === '') throw new Error(`${arg} needs a value`);
      opts[arg.slice(2)] = value;
    } else if (arg === '--watch') opts.watch = true;
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  const concurrency = Number(opts.concurrency);
  if (!Number.isInteger(concurrency) || concurrency < 1) {
    throw new Error(`--concurrency needs a positive integer`);
  }
  opts.concurrency = concurrency;
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

/** Directory list of a source tree; used by watch mode to keep watchers in sync. */
export async function listDirs(root) {
  const dirs = [];
  const visit = async (dir) => {
    dirs.push(dir);
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.isDirectory()) await visit(path.join(dir, entry.name));
    }
  };
  await visit(root);
  return dirs.sort();
}

/**
 * Resolve a dependency specifier relative to the file that contains it.
 *
 * Returns `null` when the specifier does not point into the source tree
 * (absolute paths, URLs, `data:`, fragments, package specifiers). Those are
 * passed through untouched and never tracked as a dependency.
 */
function resolveDep(rel, spec) {
  const clean = spec.split(/[?#]/, 1)[0].trim();
  if (!clean) return null;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(clean)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), clean));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha1Hex(bytes).slice(0, 8)}${ext}`;
}

/** Resolve an output-relative path, refusing anything that escapes `outDir`. */
function outPath(outDir, rel) {
  const abs = path.resolve(outDir, rel);
  const root = path.resolve(outDir);
  if (abs !== root && !abs.startsWith(root + path.sep)) return null;
  return abs;
}

async function exists(abs) {
  try {
    await stat(abs);
    return true;
  } catch {
    return false;
  }
}

const TEXT_EXTS = new Set(['.js', '.mjs', '.css', '.json']);

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  // Read every source once: the fingerprint is the content hash, so the bytes
  // are needed anyway and the rest of the plan works from memory.
  const bytes = new Map();
  for (const rel of sources) bytes.set(rel, await readFile(path.join(srcDir, rel)));

  const keys = new Map();
  const deps = new Map();
  for (const rel of sources) {
    const ext = path.posix.extname(rel);
    keys.set(rel, cacheKey(bytes.get(rel)));
    const resolved = {};
    if (TEXT_EXTS.has(ext)) {
      const text = bytes.get(rel).toString('utf8');
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

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of sources) {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const ext = path.posix.extname(rel);

    // An entry is only reusable if every file it claims to have produced is
    // still on disk; otherwise the manifest names outputs that do not exist and
    // would never heal.
    const prevOut = prev ? [...new Set([rel, ...(prev.out?.length ? prev.out : [rel])])] : [];
    let missingOutput = false;
    for (const outRel of prevOut) {
      const abs = outPath(outDir, outRel);
      if (!abs || !(await exists(abs))) {
        missingOutput = true;
        break;
      }
    }

    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const dirty = !prev || prev.key !== key || stale || missingOutput;

    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prevOut };
      continue;
    }

    built.push(rel);
    const outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      const text = bytes.get(rel).toString('utf8');
      outputs.set(rel, `${text.trimEnd()}\n//# build ${sha1Hex(text).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = bytes.get(rel).toString('utf8');
      const names = new Map();
      for (const match of text.matchAll(urlRe())) {
        const target = match[1];
        const relTarget = resolveDep(rel, target);
        if (!relTarget) continue; // URL, absolute path, fragment: leave it alone
        const targetBytes = bytes.get(relTarget);
        if (!targetBytes) continue; // missing local asset: stays as-is, dep records 'missing'
        const name = hashedName(relTarget, targetBytes);
        const outRel = path.posix.join(path.posix.dirname(rel), name);
        names.set(target, name);
        outputs.set(outRel, targetBytes);
        outNames.push(outRel);
      }
      outputs.set(rel, text.replace(urlRe(), (whole, target) => `url(${names.get(target) ?? target})`));
    } else if (ext === '.json') {
      const own = JSON.parse(bytes.get(rel).toString('utf8'));
      let merged = own;
      if (own && typeof own.extends === 'string') {
        const relBase = resolveDep(rel, own.extends);
        const baseBytes = relBase ? bytes.get(relBase) : undefined;
        if (!baseBytes) throw new Error(`${rel}: cannot resolve extends "${own.extends}"`);
        const base = JSON.parse(baseBytes.toString('utf8'));
        const { extends: dropped, ...rest } = own;
        merged = { ...base, ...rest };
      }
      outputs.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
    } else {
      outputs.set(rel, bytes.get(rel));
    }
    nextFiles[rel] = { key, deps: resolved, out: outNames };
  }

  // Every path the next manifest claims to own. Anything the previous manifest
  // owned that is not in here is garbage: a deleted source, or a hashed asset
  // whose content changed.
  const keep = new Set();
  for (const entry of Object.values(nextFiles)) for (const outRel of entry.out) keep.add(outRel);

  const previousPaths = new Set();
  for (const [rel, entry] of Object.entries(manifest.files)) {
    previousPaths.add(rel);
    for (const outRel of entry.out) previousPaths.add(outRel);
  }
  const staleOutputs = [...previousPaths].filter((outRel) => !keep.has(outRel)).sort();

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles)).sort();

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    staleOutputs,
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

async function pruneEmptyDirs(outDir, abs) {
  let dir = path.dirname(abs);
  const root = path.resolve(outDir);
  while (dir !== root && dir.startsWith(root + path.sep)) {
    try {
      await rmdir(dir);
    } catch {
      return; // not empty (or gone): stop climbing
    }
    dir = path.dirname(dir);
  }
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

  const entries = [...plan.outputs];
  await mapLimit(entries, opts.concurrency ?? DEFAULT_CONCURRENCY, async ([rel, content]) => {
    const abs = outPath(plan.outDir, rel);
    if (!abs) throw new Error(`refusing to write outside the output directory: ${rel}`);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });

  // Delete before the manifest is committed: if we crash here the manifest still
  // lists the old outputs, so the next build re-derives and re-deletes them.
  for (const rel of plan.staleOutputs) {
    const abs = outPath(plan.outDir, rel);
    if (!abs) continue;
    try {
      await unlink(abs);
    } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
    await pruneEmptyDirs(plan.outDir, abs);
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
