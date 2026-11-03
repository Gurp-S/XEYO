import { readdir, readFile, stat, mkdir, writeFile, unlink, rmdir } from 'node:fs/promises';
import path from 'node:path';
import { collectDeps } from './graph.js';
import { fingerprint } from './cache.js';
import { mapLimit } from './concurrency.js';
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
  --concurrency <n>    max files built at once (default: 4)
  --watch              keep running and rebuild when sources change
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
    else if (arg === '--concurrency') {
      const raw = argv[(index += 1)];
      if (!/^\d+$/.test(raw ?? '') || Number(raw) < 1) {
        throw new Error('--concurrency needs a positive integer');
      }
      opts.concurrency = Number(raw);
    } else if (arg === '--watch') opts.watch = true;
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

function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${fingerprint(bytes).slice(0, 8)}${ext}`;
}

const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

async function exists(abs) {
  try {
    await stat(abs);
    return true;
  } catch {
    return false;
  }
}

async function pruneEmpty(dir, stopAt) {
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

function describe(plan, dryRun, started) {
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun,
    durationMs: Date.now() - started,
  };
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  // Fingerprints come from bytes, never from mtime: a file rewritten in place
  // with an unchanged timestamp must still be rebuilt.
  const bytes = new Map();
  await mapLimit(sources, limit, async (rel) => {
    bytes.set(rel, await readFile(path.join(srcDir, rel)));
  });

  const keys = new Map();
  const deps = new Map();
  for (const rel of sources) {
    const buf = bytes.get(rel);
    keys.set(rel, fingerprint(buf));
    const ext = path.posix.extname(rel);
    const resolved = {};
    for (const spec of collectDeps(buf.toString('utf8'), ext)) {
      const target = resolveDep(rel, spec);
      if (target) resolved[target] = bytes.has(target) ? keys.get(target) : 'missing';
    }
    deps.set(rel, resolved);
  }

  const recordedDeps = (entry) => (entry && entry.deps && typeof entry.deps === 'object' ? entry.deps : {});

  async function upToDate(rel) {
    const entry = manifest.files[rel];
    if (!entry || entry.key !== keys.get(rel)) return false;
    const before = recordedDeps(entry);
    const after = deps.get(rel) ?? {};
    for (const dep of new Set([...Object.keys(before), ...Object.keys(after)])) {
      if (before[dep] !== after[dep]) return false;
    }
    const outs = Array.isArray(entry.out) ? entry.out : [];
    if (outs.length === 0) return false;
    // A manifest that names outputs which no longer exist is not a reason to
    // skip: the output has to be produced again.
    for (const out of outs) {
      if (!(await exists(path.join(outDir, out)))) return false;
    }
    return true;
  }

  const fresh = new Map();
  await mapLimit(sources, limit, async (rel) => {
    fresh.set(rel, await upToDate(rel));
  });

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of sources) {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    if (fresh.get(rel)) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: [...manifest.files[rel].out] };
      continue;
    }
    built.push(rel);
    const buf = bytes.get(rel);
    const ext = path.posix.extname(rel);
    const outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      const text = buf.toString('utf8');
      outputs.set(rel, `${text.trimEnd()}\n//# build ${fingerprint(text).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const text = buf.toString('utf8');
      const names = new Map();
      for (const match of text.matchAll(URL_RE)) {
        const target = match[1];
        const relTarget = resolveDep(rel, target);
        if (!relTarget || !bytes.has(relTarget)) continue;
        const name = hashedName(relTarget, bytes.get(relTarget));
        names.set(target, name);
        outputs.set(name, bytes.get(relTarget));
        outNames.push(name);
      }
      outputs.set(
        rel,
        text.replace(URL_RE, (whole, target) => (names.has(target) ? `url(${names.get(target)})` : whole)),
      );
    } else if (ext === '.json') {
      const own = JSON.parse(buf.toString('utf8'));
      let merged = own;
      if (own && typeof own.extends === 'string') {
        const relBase = resolveDep(rel, own.extends);
        if (!relBase || !bytes.has(relBase)) {
          throw new Error(`missing extends base: ${own.extends} referenced from ${rel}`);
        }
        const base = JSON.parse(bytes.get(relBase).toString('utf8'));
        const { extends: dropped, ...rest } = own;
        merged = { ...base, ...rest };
      }
      outputs.set(rel, `${JSON.stringify(merged, null, 2)}\n`);
    } else {
      outputs.set(rel, buf);
    }
    nextFiles[rel] = { key, deps: resolved, out: outNames };
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));

  const previousOutputs = new Set();
  for (const entry of Object.values(manifest.files)) {
    if (entry && Array.isArray(entry.out)) for (const out of entry.out) previousOutputs.add(out);
  }
  const currentOutputs = new Set();
  for (const entry of Object.values(nextFiles)) {
    for (const out of entry.out) currentOutputs.add(out);
  }
  const staleOutputs = [...previousOutputs].filter((out) => !currentOutputs.has(out)).sort();

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

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) return describe(plan, true, started);

  await mkdir(plan.outDir, { recursive: true });
  await mapLimit([...plan.outputs], limit, async ([rel, content]) => {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  await mapLimit(plan.staleOutputs, limit, async (rel) => {
    const abs = path.join(plan.outDir, rel);
    await unlink(abs).catch(() => {});
    await pruneEmpty(path.dirname(abs), plan.outDir);
  });
  // The manifest goes last and is written atomically, so a crash can only
  // leave stale-but-valid bookkeeping that the next build heals, never a
  // truncated manifest and never entries for outputs that were not written.
  await saveManifest(plan.manifestPath, plan.next);
  return describe(plan, false, started);
}
