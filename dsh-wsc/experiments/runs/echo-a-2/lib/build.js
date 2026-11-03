import { readdir, readFile, stat, mkdir, writeFile, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { readDeps, URL_RE } from './graph.js';
import { cacheKey } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

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
  --concurrency <n>    build at most n files at a time (default: ${DEFAULT_CONCURRENCY})
  --watch              rebuild whenever a source file changes
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --help, -h           show this help
`;

function readValue(argv, index, flag) {
  const value = argv[index];
  if (value === undefined) throw new Error(`${flag} needs a value`);
  return value;
}

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: DEFAULT_CONCURRENCY,
    dryRun: false,
    json: false,
    help: false,
    watch: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = readValue(argv, (index += 1), '--src');
    else if (arg === '--out') opts.out = readValue(argv, (index += 1), '--out');
    else if (arg === '--manifest') opts.manifest = readValue(argv, (index += 1), '--manifest');
    else if (arg === '--concurrency') opts.concurrency = parseConcurrency(readValue(argv, (index += 1), '--concurrency'));
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  return opts;
}

function parseConcurrency(raw) {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`--concurrency needs a positive integer, got: ${raw}`);
  }
  return value;
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

// Runs at most `limit` tasks at once; results keep the input order.
async function mapLimit(items, limit, task) {
  const results = new Array(items.length);
  let cursor = 0;
  const width = Math.min(Math.max(1, limit), items.length);
  const workers = Array.from({ length: width }, async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      results[index] = await task(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}

function sha(input) {
  return createHash('sha1').update(input).digest('hex');
}

// A specifier resolves to a source path only when it stays inside the tree;
// URLs, data: URIs, root paths and fragments are left untouched.
function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(spec)) return null;
  const clean = spec.split(/[?#]/)[0];
  if (!clean) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), clean));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha(bytes).slice(0, 8)}${ext}`;
}

// Guards the manifest against entries that would escape the output tree.
function safeOut(outDir, rel) {
  if (typeof rel !== 'string') return null;
  const abs = path.resolve(outDir, rel);
  const inside = path.relative(outDir, abs);
  if (!inside || inside.startsWith('..') || path.isAbsolute(inside)) return null;
  return abs;
}

async function outputsMissing(outDir, names) {
  for (const name of names ?? []) {
    const abs = safeOut(outDir, name);
    if (!abs) return true;
    try {
      if (!(await stat(abs)).isFile()) return true;
    } catch {
      return true;
    }
  }
  return false;
}

function sameDeps(previous, current) {
  const left = previous ?? {};
  const keys = new Set([...Object.keys(left), ...Object.keys(current)]);
  for (const key of keys) if (left[key] !== current[key]) return false;
  return true;
}

function mergeExtends(bytes, rel, seen = new Set()) {
  if (seen.has(rel)) throw new Error(`circular extends: ${[...seen, rel].join(' -> ')}`);
  const own = JSON.parse(bytes.get(rel).toString('utf8'));
  if (!own || typeof own !== 'object' || typeof own.extends !== 'string') return own;
  const baseRel = resolveDep(rel, own.extends);
  if (!baseRel || !bytes.has(baseRel)) return own;
  seen.add(rel);
  const base = mergeExtends(bytes, baseRel, seen);
  const { extends: dropped, ...rest } = own;
  return { ...base, ...rest };
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  // The fingerprint is a hash of the bytes, so a rewrite that keeps the old
  // size and mtime still invalidates the cached output.
  const bytes = new Map();
  const keys = new Map();
  await mapLimit(sources, limit, async (rel) => {
    const content = await readFile(path.join(srcDir, rel));
    bytes.set(rel, content);
    keys.set(rel, cacheKey(content));
  });

  const deps = new Map();
  for (const rel of sources) {
    const resolved = {};
    for (const spec of readDeps(path.posix.extname(rel), bytes.get(rel))) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = keys.get(target) ?? 'missing';
    }
    deps.set(rel, resolved);
  }

  const outputs = new Map();
  const stale = new Set();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of sources) {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const changed = !prev || prev.key !== key || !sameDeps(prev.deps, resolved);
    // A manifest can name outputs that no longer exist; that never heals
    // unless a missing output counts as a reason to rebuild.
    const lost = !changed && (await outputsMissing(outDir, prev.out));
    if (!changed && !lost) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out };
      continue;
    }

    built.push(rel);
    const content = bytes.get(rel);
    const ext = path.posix.extname(rel);
    const outNames = new Set([rel]);

    if (ext === '.js' || ext === '.mjs') {
      const text = content.toString('utf8');
      outputs.set(rel, `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = content.toString('utf8');
      const names = new Map();
      for (const match of text.matchAll(new RegExp(URL_RE.source, 'g'))) {
        const target = match[1];
        const relTarget = resolveDep(rel, target);
        if (!relTarget || !bytes.has(relTarget)) continue;
        const asset = bytes.get(relTarget);
        const name = hashedName(relTarget, asset);
        names.set(target, name);
        outputs.set(name, asset);
        outNames.add(name);
      }
      outputs.set(
        rel,
        text.replace(new RegExp(URL_RE.source, 'g'), (whole, target) =>
          names.has(target) ? `url(${names.get(target)})` : whole,
        ),
      );
    } else if (ext === '.json') {
      outputs.set(rel, `${JSON.stringify(mergeExtends(bytes, rel), null, 2)}\n`);
    } else {
      outputs.set(rel, content);
    }

    // Outputs this source used to produce but no longer does (a renamed
    // hashed asset, for instance) must not linger.
    for (const name of prev?.out ?? []) if (!outNames.has(name)) stale.add(name);
    nextFiles[rel] = { key, deps: resolved, out: [...outNames] };
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  for (const rel of removed) {
    for (const name of manifest.files[rel].out ?? []) stale.add(name);
  }
  // Never delete a path this build just produced.
  for (const name of outputs.keys()) stale.delete(name);

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    removed,
    stale: [...stale],
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
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
  await mapLimit([...plan.outputs], limit, async ([rel, content]) => {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  await mapLimit(plan.stale, limit, async (rel) => {
    const abs = safeOut(plan.outDir, rel);
    if (abs) await rm(abs, { force: true });
  });
  // The manifest lands last and atomically, so it can never describe a build
  // that did not finish.
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
