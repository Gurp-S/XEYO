import { existsSync } from 'node:fs';
import { readdir, readFile, stat, mkdir, writeFile, rename, rm, readdir as readDirAsync } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { depSpecifiers, resolveDep, rewriteUrls } from './graph.js';
import { fingerprint, shortHash } from './cache.js';
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
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${shortHash(bytes)}${ext}`;
}

function parseJson(rel, sources) {
  const bytes = sources.get(rel);
  if (!bytes) return null;
  try {
    return JSON.parse(bytes.toString('utf8'));
  } catch {
    return null;
  }
}

// `extends` is resolved transitively so a chain base -> mid -> derived merges in
// order and never leaks the `extends` key into an output.
function mergeJson(rel, sources, seen = new Set()) {
  const own = parseJson(rel, sources);
  if (!own || typeof own !== 'object' || Array.isArray(own) || typeof own.extends !== 'string') return own;
  const { extends: dropped, ...rest } = own;
  const baseRel = resolveDep(rel, dropped);
  if (!baseRel || !sources.has(baseRel)) return rest;
  if (seen.has(baseRel)) throw new Error(`circular "extends" chain: ${[...seen, baseRel].join(' -> ')}`);
  const base = mergeJson(baseRel, sources, new Set([...seen, baseRel]));
  return base && typeof base === 'object' && !Array.isArray(base) ? { ...base, ...rest } : rest;
}

function outputFor(rel, ext, sources) {
  const bytes = sources.get(rel);
  const out = new Map();
  if (ext === '.js' || ext === '.mjs') {
    const text = bytes.toString('utf8');
    const trimmed = text.trimEnd();
    out.set(rel, `${trimmed ? `${trimmed}\n` : ''}//# build ${shortHash(bytes)}\n`);
  } else if (ext === '.css') {
    const assets = new Map();
    const text = bytes.toString('utf8');
    const rewritten = rewriteUrls(text, (target) => {
      const targetRel = resolveDep(rel, target);
      if (!targetRel || !sources.has(targetRel)) return null;
      const assetBytes = sources.get(targetRel);
      const name = hashedName(targetRel, assetBytes);
      assets.set(name, assetBytes);
      return name;
    });
    out.set(rel, rewritten);
    for (const [name, assetBytes] of assets) out.set(name, assetBytes);
  } else if (ext === '.json') {
    out.set(rel, `${JSON.stringify(mergeJson(rel, sources), null, 2)}\n`);
  } else {
    out.set(rel, bytes);
  }
  return out;
}

function dependenciesOf(rel, ext, sources, keys) {
  const specs = depSpecifiers(rel, ext, sources.get(rel));
  const targets = new Set();
  for (const spec of specs) {
    const target = resolveDep(rel, spec);
    if (target) targets.add(target);
  }
  if (ext === '.json') {
    const seen = new Set([rel]);
    let cursor = rel;
    for (;;) {
      const data = parseJson(cursor, sources);
      if (!data || typeof data !== 'object' || Array.isArray(data) || typeof data.extends !== 'string') break;
      const next = resolveDep(cursor, data.extends);
      if (!next) break;
      if (seen.has(next)) throw new Error(`circular "extends" chain: ${[...seen, next].join(' -> ')}`);
      seen.add(next);
      targets.add(next);
      cursor = next;
    }
  }
  const resolved = {};
  for (const target of [...targets].sort()) resolved[target] = keys.get(target) ?? 'missing';
  return resolved;
}

function sameDeps(a, b) {
  const left = a && typeof a === 'object' ? a : {};
  const right = b && typeof b === 'object' ? b : {};
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key) => key in right && left[key] === right[key]);
}

function insideOut(outDir, rel) {
  const abs = path.resolve(outDir, rel);
  const root = path.resolve(outDir);
  return abs === root || abs.startsWith(`${root}${path.sep}`);
}

function outputsIntact(outDir, outs) {
  if (!Array.isArray(outs)) return false;
  return outs.every((rel) => insideOut(outDir, rel) && existsSync(path.resolve(outDir, rel)));
}

async function writeAtomic(abs, content) {
  const tmp = `${abs}.${process.pid}.${Date.now().toString(36)}.tmp`;
  await mkdir(path.dirname(abs), { recursive: true });
  try {
    await writeFile(tmp, content);
    await rename(tmp, abs);
  } catch (error) {
    await rm(tmp, { force: true });
    throw error;
  }
}

async function pruneEmptyParents(outDir, abs) {
  let dir = path.dirname(abs);
  const root = path.resolve(outDir);
  while (dir !== root && dir.startsWith(`${root}${path.sep}`)) {
    let entries;
    try {
      entries = await readDirAsync(dir);
    } catch {
      return;
    }
    if (entries.length > 0) return;
    try {
      await rm(dir, { recursive: false });
    } catch {
      return;
    }
    dir = path.dirname(dir);
  }
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const rels = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const sources = new Map();
  const keys = new Map();
  for (const rel of rels) {
    const bytes = await readFile(path.join(srcDir, rel));
    sources.set(rel, bytes);
    keys.set(rel, fingerprint(bytes));
  }

  const deps = new Map();
  for (const rel of rels) deps.set(rel, dependenciesOf(rel, path.posix.extname(rel), sources, keys));

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of rels) {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const dirty =
      !prev || prev.key !== key || !sameDeps(prev.deps, resolved) || !outputsIntact(outDir, prev.out);
    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out };
      continue;
    }
    built.push(rel);
    const produced = outputFor(rel, path.posix.extname(rel), sources);
    for (const [name, content] of produced) outputs.set(name, content);
    nextFiles[rel] = { key, deps: resolved, out: [...produced.keys()] };
  }

  // Outputs named by the previous manifest that this plan no longer produces:
  // deleted sources, and hashed assets whose content (and therefore name) moved.
  const previousOuts = new Set();
  for (const entry of Object.values(manifest.files)) {
    for (const name of entry?.out ?? []) previousOuts.add(name);
  }
  const currentOuts = new Set();
  for (const entry of Object.values(nextFiles)) {
    for (const name of entry.out) currentOuts.add(name);
  }
  const stale = [...previousOuts].filter((name) => !currentOuts.has(name)).sort();
  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles)).sort();

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
  // Outputs first, manifest last: an interrupted build leaves the previous
  // manifest in place, so the next run sees the missing outputs and heals them
  // instead of trusting a manifest that describes files it never wrote.
  for (const [rel, content] of plan.outputs) {
    if (!insideOut(plan.outDir, rel)) throw new Error(`output escapes the output directory: ${rel}`);
    await writeAtomic(path.resolve(plan.outDir, rel), content);
  }
  for (const rel of plan.stale) {
    if (!insideOut(plan.outDir, rel)) continue;
    const abs = path.resolve(plan.outDir, rel);
    await rm(abs, { force: true });
    await pruneEmptyParents(plan.outDir, abs);
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
