import { readFile, stat, mkdir, writeFile, rm, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { dependencySpecifiers, resolveDep, URL_RE } from './graph.js';
import { cacheKey } from './cache.js';
import { walk } from './walk.js';
import { loadRawManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

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

function sha(input) {
  return createHash('sha1').update(input).digest('hex');
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha(bytes).slice(0, 8)}${ext}`;
}

function renderJs(text) {
  return `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`;
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// The base named by `extends` is a real file, and it may extend another one, so
// the merge follows the chain and stops at the first missing or repeated file.
function mergeJson(rel, text, bytes, seen) {
  const own = JSON.parse(text);
  if (!isPlainObject(own) || typeof own.extends !== 'string') return own;
  const { extends: spec, ...rest } = own;
  const baseRel = resolveDep(rel, spec);
  let base = {};
  if (baseRel && bytes.has(baseRel) && !seen.has(baseRel)) {
    const resolved = mergeJson(baseRel, bytes.get(baseRel).toString('utf8'), bytes, new Set(seen).add(rel));
    if (isPlainObject(resolved)) base = resolved;
  }
  return { ...base, ...rest };
}

function renderJson(rel, text, bytes) {
  return `${JSON.stringify(mergeJson(rel, text, bytes, new Set()), null, 2)}\n`;
}

async function exists(file) {
  try {
    await stat(file);
    return true;
  } catch {
    return false;
  }
}

async function allOutputsPresent(outDir, names) {
  if (!Array.isArray(names) || names.length === 0) return false;
  for (const name of names) {
    if (!(await exists(path.join(outDir, name)))) return false;
  }
  return true;
}

async function pruneEmptyDirs(dir, stop) {
  let current = dir;
  while (current.startsWith(stop) && current !== stop) {
    try {
      const entries = await readdir(current);
      if (entries.length > 0) return;
      await rm(current, { recursive: false });
    } catch {
      return;
    }
    current = path.dirname(current);
  }
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const raw = await loadRawManifest(manifestPath);
  const usable = raw && raw.version === MANIFEST_VERSION ? raw : null;
  const manifest = usable ?? { version: MANIFEST_VERSION, files: {} };
  // An unusable manifest still names the outputs a previous run wrote; those
  // bytes go away unless this run reproduces them.
  const orphaned = usable ? [] : Object.values(raw?.files ?? {}).flatMap((entry) => entry?.out ?? []);

  const bytes = new Map();
  const stats = new Map();
  const deps = new Map();
  for (const rel of sources) {
    const content = await readFile(path.join(srcDir, rel));
    bytes.set(rel, content);
    stats.set(rel, cacheKey(content));
    const resolved = {};
    for (const spec of dependencySpecifiers(rel, content)) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = null;
    }
    deps.set(rel, resolved);
  }
  for (const resolved of deps.values()) {
    for (const target of Object.keys(resolved)) resolved[target] = stats.get(target) ?? 'missing';
  }

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};
  // A rebuilt file can emit a different set of names than last time (a css asset
  // hash changes, a url() reference disappears), so the old names are dropped
  // here or the tree would keep bytes that a full rebuild never produces.
  const superseded = [];

  for (const rel of sources) {
    const key = stats.get(rel);
    const content = bytes.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const intact = prev ? await allOutputsPresent(outDir, prev.out) : false;
    const dirty = !prev || prev.key !== key || stale || !intact;
    const ext = path.posix.extname(rel);

    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out };
      continue;
    }

    built.push(rel);
    const outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      outputs.set(rel, renderJs(content.toString('utf8')));
    } else if (ext === '.css') {
      const text = content.toString('utf8');
      const names = new Map();
      for (const match of text.matchAll(URL_RE)) {
        const target = match[1];
        const relTarget = resolveDep(rel, target);
        if (!relTarget || !bytes.has(relTarget)) continue;
        const asset = bytes.get(relTarget);
        const name = hashedName(relTarget, asset);
        // The hashed copy is emitted next to the stylesheet that references it,
        // so the rewritten url() stays a plain relative reference.
        const dir = path.posix.dirname(rel);
        const assetRel = dir === '.' ? name : `${dir}/${name}`;
        names.set(target, name);
        outputs.set(assetRel, asset);
        outNames.push(assetRel);
      }
      outputs.set(
        rel,
        text.replace(URL_RE, (whole, target) => (names.has(target) ? `url(${names.get(target)})` : whole)),
      );
    } else if (ext === '.json') {
      outputs.set(rel, renderJson(rel, content.toString('utf8'), bytes));
    } else {
      outputs.set(rel, content);
    }
    nextFiles[rel] = { key, deps: resolved, out: outNames };
    for (const name of prev?.out ?? []) {
      if (!outNames.includes(name)) superseded.push(name);
    }
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  const produced = new Set(Object.values(nextFiles).flatMap((entry) => entry.out ?? []));
  const removeOutputs = [
    ...removed.flatMap((rel) => manifest.files[rel]?.out ?? [rel]),
    ...superseded.filter((name) => !produced.has(name)),
    ...orphaned.filter((name) => !produced.has(name)),
  ];
  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    removed,
    removeOutputs,
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
  for (const [rel, content] of plan.outputs) {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  for (const rel of plan.removeOutputs) {
    const abs = path.join(plan.outDir, rel);
    await rm(abs, { force: true });
    await pruneEmptyDirs(path.dirname(abs), plan.outDir);
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
