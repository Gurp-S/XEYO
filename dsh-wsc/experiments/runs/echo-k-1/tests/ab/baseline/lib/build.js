import { readdir, readFile, stat, mkdir, writeFile } from 'node:fs/promises';
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

function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha(bytes).slice(0, 8)}${ext}`;
}

const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const stats = new Map();
  const deps = new Map();
  for (const rel of sources) {
    const abs = path.join(srcDir, rel);
    const info = await stat(abs);
    stats.set(rel, cacheKey(info));
    const specifiers = await readDeps(abs, path.posix.extname(rel));
    const resolved = {};
    for (const spec of specifiers) {
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

  for (const rel of sources) {
    const key = stats.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const dirty = !prev || prev.key !== key || stale;
    const ext = path.posix.extname(rel);
    const outNames = [rel];
    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out ?? outNames };
      continue;
    }
    built.push(rel);
    const abs = path.join(srcDir, rel);
    if (ext === '.js' || ext === '.mjs') {
      const text = await readFile(abs, 'utf8');
      outputs.set(rel, `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = await readFile(abs, 'utf8');
      const names = new Map();
      for (const match of text.matchAll(URL_RE)) {
        const target = match[1];
        const relTarget = resolveDep(rel, target);
        const bytes = await readFile(path.join(srcDir, relTarget));
        const name = hashedName(relTarget, bytes);
        names.set(target, name);
        outputs.set(name, bytes);
        outNames.push(name);
      }
      outputs.set(rel, text.replace(URL_RE, (whole, target) => `url(${names.get(target) ?? target})`));
    } else if (ext === '.json') {
      const own = JSON.parse(await readFile(abs, 'utf8'));
      let merged = own;
      if (own && typeof own.extends === 'string') {
        const relBase = resolveDep(rel, own.extends);
        const base = JSON.parse(await readFile(path.join(srcDir, relBase), 'utf8'));
        const { extends: dropped, ...rest } = own;
        merged = { ...base, ...rest };
      }
      outputs.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
    } else {
      outputs.set(rel, await readFile(abs));
    }
    nextFiles[rel] = { key, deps: resolved, out: outNames };
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
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
  await saveManifest(plan.manifestPath, plan.next);
  for (const [rel, content] of plan.outputs) {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun: false,
    durationMs: Date.now() - started,
  };
}
