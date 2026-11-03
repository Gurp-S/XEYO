import { readdir, readFile, mkdir, writeFile, rm, rmdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { readDeps } from './graph.js';
import { cacheKey } from './cache.js';
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

function sha(input) {
  return createHash('sha1').update(input).digest('hex');
}

function isRelativeSpec(spec) {
  return /^\.{1,2}\//.test(spec);
}

function resolveDep(rel, spec, relativeOnly) {
  if (typeof spec !== 'string' || spec === '') return null;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  if (relativeOnly && !isRelativeSpec(spec)) return null;
  const target = path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
  if (target === '.' || target === '..' || target.startsWith('../')) return null;
  return target;
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha(bytes).slice(0, 8)}${ext}`;
}

function isInside(root, abs) {
  const rel = path.relative(root, abs);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

async function pruneEmptyDirs(start, root) {
  let dir = path.dirname(start);
  while (dir !== root && dir.startsWith(`${root}${path.sep}`)) {
    try {
      await rmdir(dir);
    } catch {
      return;
    }
    dir = path.dirname(dir);
  }
}

const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;
const RELATIVE_ONLY_DEPS = new Set(['.js', '.mjs']);

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  // Read every source once: content hashes are the fingerprint, and the same
  // bytes are reused for rendering so a file can never change mid-build.
  const contents = new Map();
  const fingerprints = new Map();
  const depSpecs = new Map();
  for (const rel of sources) {
    const abs = path.join(srcDir, rel);
    const bytes = await readFile(abs);
    contents.set(rel, bytes);
    fingerprints.set(rel, cacheKey(bytes));
    depSpecs.set(rel, await readDeps(abs, path.posix.extname(rel)));
  }

  const deps = new Map();
  for (const rel of sources) {
    const relativeOnly = RELATIVE_ONLY_DEPS.has(path.posix.extname(rel));
    const resolved = {};
    for (const spec of depSpecs.get(rel)) {
      const target = resolveDep(rel, spec, relativeOnly);
      if (target) resolved[target] = fingerprints.get(target) ?? 'missing';
    }
    deps.set(rel, resolved);
  }

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = Object.create(null);

  for (const rel of sources) {
    const key = fingerprints.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = Object.hasOwn(manifest.files, rel) ? manifest.files[rel] : undefined;
    const depsChanged = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const dirty = !prev || prev.key !== key || depsChanged;
    const ext = path.posix.extname(rel);
    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out ?? [rel] };
      continue;
    }

    built.push(rel);
    const outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      const text = contents.get(rel).toString('utf8');
      outputs.set(rel, `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = contents.get(rel).toString('utf8');
      const names = new Map();
      URL_RE.lastIndex = 0;
      for (const match of text.matchAll(URL_RE)) {
        const spec = match[1];
        const relTarget = resolveDep(rel, spec, false);
        const bytes = relTarget ? contents.get(relTarget) : undefined;
        if (!bytes) continue;
        const outPath = path.posix.join(path.posix.dirname(rel), hashedName(relTarget, bytes));
        names.set(spec, path.posix.basename(outPath));
        outputs.set(outPath, bytes);
        if (!outNames.includes(outPath)) outNames.push(outPath);
      }
      outputs.set(rel, text.replace(URL_RE, (whole, spec) => (names.has(spec) ? `url(${names.get(spec)})` : whole)));
    } else if (ext === '.json') {
      const own = JSON.parse(contents.get(rel).toString('utf8'));
      let merged = own;
      const relBase = own && typeof own.extends === 'string' ? resolveDep(rel, own.extends, false) : null;
      if (relBase) {
        const baseBytes = contents.get(relBase);
        if (!baseBytes) throw new Error(`missing dependency: ${relBase} (extends, referenced by ${rel})`);
        const base = JSON.parse(baseBytes.toString('utf8'));
        const { extends: dropped, ...rest } = own;
        merged = { ...base, ...rest };
      }
      outputs.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
    } else {
      outputs.set(rel, contents.get(rel));
    }
    nextFiles[rel] = { key, deps: resolved, out: outNames };
  }

  const kept = new Set();
  for (const entry of Object.values(nextFiles)) {
    for (const out of entry.out ?? []) kept.add(out);
  }
  const staleSet = new Set();
  for (const entry of Object.values(manifest.files)) {
    for (const out of entry.out ?? []) {
      if (!kept.has(out)) staleSet.add(out);
    }
  }

  const removed = Object.keys(manifest.files)
    .filter((rel) => !Object.hasOwn(nextFiles, rel))
    .sort();

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    stale: [...staleSet].sort(),
    removed,
    built,
    skipped,
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

  await mkdir(plan.outDir, { recursive: true });
  for (const [rel, content] of plan.outputs) {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  for (const rel of plan.stale) {
    const abs = path.resolve(plan.outDir, rel);
    if (!isInside(plan.outDir, abs)) continue;
    try {
      await rm(abs, { force: true });
    } catch {
      continue;
    }
    await pruneEmptyDirs(abs, plan.outDir);
  }
  await saveManifest(plan.manifestPath, plan.next);
  report.durationMs = Date.now() - started;
  return report;
}
