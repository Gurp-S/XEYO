import { mkdir, readdir, readFile, rm, rmdir, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { readDeps, URL_RE } from './graph.js';
import { resolveDep } from './resolve.js';
import { contentKey, shortHash } from './fingerprint.js';
import { MANIFEST_VERSION, loadManifest, saveManifest } from './manifest.js';
import { mapLimit } from './pool.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 4;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>        source directory (default: src)
  --out <dir>        output directory (default: out)
  --manifest <file>  build manifest path (default: build-manifest.json)
  --concurrency <n>  build at most n files at once (default: ${DEFAULT_CONCURRENCY})
  --dry-run          report the plan without writing anything
  --watch            rebuild whenever the source tree changes
  --json             print a machine-readable report
  --help, -h         show this help
`;

function parseConcurrency(value) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1) {
    throw new Error(`--concurrency needs a positive integer, got: ${value ?? '(nothing)'}`);
  }
  return number;
}

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
    else if (arg === '--concurrency') opts.concurrency = parseConcurrency(argv[(index += 1)]);
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

async function walk(dir, root) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, root)));
    else if (entry.isFile()) files.push(path.relative(root, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const stem = rel.slice(0, rel.length - ext.length);
  return `${stem}.${shortHash(bytes)}${ext}`;
}

function sameDeps(previous, next) {
  const keys = Object.keys(next);
  if (Object.keys(previous).length !== keys.length) return false;
  return keys.every((key) => previous[key] === next[key]);
}

async function anyMissing(outDir, names) {
  for (const name of names) {
    try {
      await stat(path.join(outDir, name));
    } catch {
      return true;
    }
  }
  return false;
}

function transform(rel, bytes, sourceBytes, sourceSet) {
  const ext = path.posix.extname(rel);
  const extra = [];
  let content;

  if (ext === '.js' || ext === '.mjs') {
    content = `${bytes.toString('utf8').trimEnd()}\n//# build ${shortHash(bytes)}\n`;
  } else if (ext === '.css') {
    const text = bytes.toString('utf8');
    const names = new Map();
    for (const match of text.matchAll(URL_RE)) {
      const target = match[1];
      const relTarget = resolveDep(rel, target, ext);
      if (!relTarget || !sourceSet.has(relTarget)) continue;
      const targetBytes = sourceBytes.get(relTarget);
      const name = hashedName(relTarget, targetBytes);
      names.set(target, name);
      if (!extra.some((item) => item.name === name)) extra.push({ name, bytes: targetBytes });
    }
    content = text.replace(URL_RE, (whole, target) => (names.has(target) ? `url(${names.get(target)})` : whole));
  } else if (ext === '.json') {
    const own = JSON.parse(bytes.toString('utf8'));
    let merged = own;
    if (own && typeof own.extends === 'string') {
      const relBase = resolveDep(rel, own.extends, ext);
      if (!relBase || relBase === rel || !sourceSet.has(relBase)) {
        throw new Error(`${rel}: extends target not found: ${own.extends}`);
      }
      const base = JSON.parse(sourceBytes.get(relBase).toString('utf8'));
      const { extends: dropped, ...rest } = own;
      merged = { ...base, ...rest };
    }
    content = `${JSON.stringify(merged, null, 2)}\n`;
  } else {
    content = bytes;
  }

  return { rel, content, extra, out: [rel, ...extra.map((item) => item.name)] };
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;

  const sources = await walk(srcDir, srcDir);
  const sourceSet = new Set(sources);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const sourceBytes = new Map();
  const keys = new Map();
  const deps = new Map();
  await mapLimit(sources, limit, async (rel) => {
    const bytes = await readFile(path.join(srcDir, rel));
    sourceBytes.set(rel, bytes);
    keys.set(rel, contentKey(bytes));
  });
  await mapLimit(sources, limit, async (rel) => {
    const resolved = {};
    const ext = path.posix.extname(rel);
    for (const spec of readDeps(sourceBytes.get(rel), ext)) {
      const target = resolveDep(rel, spec, ext);
      if (!target) continue;
      resolved[target] = sourceSet.has(target) ? contentKey(sourceBytes.get(target)) : 'missing';
    }
    deps.set(rel, resolved);
  });

  const dirty = [];
  const clean = [];
  for (const rel of sources) {
    const prev = manifest.files[rel];
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const outputsMissing =
      !prev || !Array.isArray(prev.out) || prev.out.length === 0 || (await anyMissing(outDir, prev.out));
    if (!prev || prev.key !== key || !sameDeps(prev.deps ?? {}, resolved) || outputsMissing) dirty.push(rel);
    else clean.push(rel);
  }

  const produced = await mapLimit(dirty, limit, (rel) =>
    transform(rel, sourceBytes.get(rel), sourceBytes, sourceSet),
  );

  const outputs = new Map();
  const nextFiles = {};
  for (const rel of sources) {
    nextFiles[rel] = { key: keys.get(rel), deps: deps.get(rel) ?? {}, out: manifest.files[rel]?.out ?? [rel] };
  }
  for (const item of produced) {
    for (const asset of item.extra) outputs.set(asset.name, asset.bytes);
    outputs.set(item.rel, item.content);
    nextFiles[item.rel] = { key: keys.get(item.rel), deps: deps.get(item.rel) ?? {}, out: item.out };
  }

  const removed = Object.keys(manifest.files)
    .filter((rel) => !(rel in nextFiles))
    .sort();

  // Outputs nobody references any more: those of deleted sources, plus hashed
  // assets a rebuild stopped producing. Without this the tree keeps drifting
  // away from what a clean build would write.
  const producedNames = new Set();
  for (const entry of Object.values(nextFiles)) for (const name of entry.out) producedNames.add(name);
  const staleOutputs = new Set();
  const addStale = (names) => {
    for (const name of names ?? []) if (!producedNames.has(name)) staleOutputs.add(name);
  };
  for (const rel of removed) addStale(manifest.files[rel]?.out ?? [rel]);
  for (const item of produced) addStale(manifest.files[item.rel]?.out);

  return {
    srcDir,
    outDir,
    manifestPath,
    built: dirty,
    skipped: clean,
    removed,
    staleOutputs: [...staleOutputs].sort(),
    outputs,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

async function pruneEmptyDirs(dir) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const child = path.join(dir, entry.name);
    await pruneEmptyDirs(child);
    try {
      if ((await readdir(child)).length === 0) await rmdir(child);
    } catch {
      // raced or not empty any more: leave it alone
    }
  }
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
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
  await mapLimit(plan.staleOutputs, limit, (name) => rm(path.join(plan.outDir, name), { force: true }));
  if (plan.staleOutputs.length > 0) await pruneEmptyDirs(plan.outDir);
  await mapLimit(plan.outputs, limit, async ([rel, content]) => {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  });
  // Manifest last and atomically: an interrupted build must never claim work it
  // did not finish, and a truncated manifest must never crash the next build.
  await saveManifest(plan.manifestPath, plan.next);

  report.durationMs = Date.now() - started;
  return report;
}
