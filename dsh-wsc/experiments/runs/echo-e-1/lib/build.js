import { readdir, readFile, stat, mkdir, writeFile, unlink } from 'node:fs/promises';
import path from 'node:path';
import { depSpecs, isTextExtension, URL_RE } from './graph.js';
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

const PROTOCOL_RE = /^(?:[a-z][a-z0-9+.-]*:|\/)/i;
const IMPORT_EXTENSIONS = ['.js', '.mjs', '.css', '.json'];

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

function splitSuffix(spec) {
  const cut = spec.search(/[?#]/);
  return cut < 0 ? [spec, ''] : [spec.slice(0, cut), spec.slice(cut)];
}

function isRelativeSpec(spec) {
  return spec === '.' || spec === '..' || spec.startsWith('./') || spec.startsWith('../');
}

function locate(rel, spec, sources, { allowBare, extensions }) {
  const [clean] = splitSuffix(spec);
  if (!clean) return null;
  if (PROTOCOL_RE.test(clean)) return null;
  if (!allowBare && !isRelativeSpec(clean)) return null;
  const target = path.posix.normalize(path.posix.join(path.posix.dirname(rel), clean));
  if (target === '..' || target.startsWith('../') || target.startsWith('/')) return null;
  if (sources.has(target)) return target;
  for (const ext of extensions ?? []) {
    if (sources.has(target + ext)) return target + ext;
  }
  return target;
}

function locateImport(rel, spec, sources) {
  return locate(rel, spec, sources, { allowBare: false, extensions: IMPORT_EXTENSIONS });
}

function locateUrl(rel, spec, sources) {
  return locate(rel, spec, sources, { allowBare: true, extensions: [] });
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${cacheKey(bytes).slice(0, 8)}${ext}`;
}

function sameDeps(prev, next) {
  if (!prev || typeof prev !== 'object') return false;
  const prevKeys = Object.keys(prev);
  const nextKeys = Object.keys(next);
  if (prevKeys.length !== nextKeys.length) return false;
  return nextKeys.every((key) => prev[key] === next[key]);
}

async function outputsPresent(outDir, out) {
  if (!Array.isArray(out) || out.length === 0) return false;
  for (const outRel of out) {
    try {
      if (!(await stat(path.join(outDir, outRel))).isFile()) return false;
    } catch {
      return false;
    }
  }
  return true;
}

async function mergeJson(srcDir, rel, text, seen) {
  const own = JSON.parse(text);
  if (!own || typeof own !== 'object' || Array.isArray(own)) return own;
  if (typeof own.extends !== 'string') return own;
  if (seen.has(rel)) throw new Error(`circular extends: ${[...seen, rel].join(' -> ')}`);
  seen.add(rel);
  const baseRel = locateImport(rel, own.extends, new Set());
  const baseText = await readFile(path.join(srcDir, baseRel), 'utf8');
  const base = await mergeJson(srcDir, baseRel, baseText, seen);
  seen.delete(rel);
  const { extends: dropped, ...rest } = own;
  void dropped;
  return base && typeof base === 'object' && !Array.isArray(base) ? { ...base, ...rest } : rest;
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const rels = await walk(srcDir, srcDir);
  const sources = new Set(rels);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const contents = new Map();
  const keys = new Map();
  for (const rel of rels) {
    const bytes = await readFile(path.join(srcDir, rel));
    contents.set(rel, bytes);
    keys.set(rel, cacheKey(bytes));
  }

  const deps = new Map();
  for (const rel of rels) {
    const ext = path.posix.extname(rel).toLowerCase();
    const specs = isTextExtension(ext) ? depSpecs(ext, contents.get(rel).toString('utf8')) : [];
    const isImport = ext === '.js' || ext === '.mjs';
    const targets = new Set();
    for (const spec of specs) {
      const target = isImport ? locateImport(rel, spec, sources) : locateUrl(rel, spec, sources);
      if (target) targets.add(target);
    }
    const resolved = {};
    for (const target of [...targets].sort()) resolved[target] = keys.get(target) ?? 'missing';
    deps.set(rel, resolved);
  }

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of rels) {
    const key = keys.get(rel);
    const resolved = deps.get(rel);
    const prev = manifest.files[rel];
    const clean =
      prev &&
      prev.key === key &&
      sameDeps(prev.deps, resolved) &&
      (await outputsPresent(outDir, prev.out));
    if (clean) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out ?? [rel] };
      continue;
    }

    built.push(rel);
    const ext = path.posix.extname(rel).toLowerCase();
    const outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      const text = contents.get(rel).toString('utf8');
      const trimmed = text.trimEnd();
      outputs.set(rel, `${trimmed}${trimmed ? '\n' : ''}//# build ${cacheKey(text).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = contents.get(rel).toString('utf8');
      const rewritten = new Map();
      for (const match of text.matchAll(URL_RE)) {
        const target = match[1];
        const assetRel = locateUrl(rel, target, sources);
        if (!assetRel) continue;
        const bytes = await readFile(path.join(srcDir, assetRel));
        const outRel = path.posix.join(path.posix.dirname(rel), hashedName(assetRel, bytes));
        const [clean, suffix] = splitSuffix(target);
        rewritten.set(target, path.posix.relative(path.posix.dirname(rel), outRel) + suffix || clean);
        outputs.set(outRel, bytes);
        if (!outNames.includes(outRel)) outNames.push(outRel);
      }
      outputs.set(
        rel,
        text.replace(URL_RE, (whole, target) => {
          const replacement = rewritten.get(target);
          return replacement ? `url(${replacement})` : whole;
        }),
      );
    } else if (ext === '.json') {
      const merged = await mergeJson(srcDir, rel, contents.get(rel).toString('utf8'), new Set());
      outputs.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
    } else {
      outputs.set(rel, contents.get(rel));
    }
    nextFiles[rel] = { key, deps: resolved, out: outNames };
  }

  const produced = new Set();
  for (const entry of Object.values(nextFiles)) {
    for (const outRel of entry.out) produced.add(outRel);
  }
  const stale = new Set();
  for (const entry of Object.values(manifest.files)) {
    for (const outRel of entry.out ?? []) {
      if (!produced.has(outRel)) stale.add(outRel);
    }
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    stale: [...stale].sort(),
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

function report(plan, dryRun, started) {
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun,
    durationMs: Date.now() - started,
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) return report(plan, true, started);
  await mkdir(plan.outDir, { recursive: true });
  for (const outRel of plan.stale) {
    try {
      await unlink(path.join(plan.outDir, outRel));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  for (const [outRel, content] of plan.outputs) {
    const abs = path.join(plan.outDir, outRel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  await saveManifest(plan.manifestPath, plan.next);
  return report(plan, false, started);
}
