import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { scanSources } from './scan.js';
import { isTextSource, URL_RE } from './deps.js';
import { buildDependencyGraph, resolveToken, splitSuffix } from './graph.js';
import { contentKey, shortHash } from './hash.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { writeFileAtomic, removeFile, isInside, pathExists, pruneEmptyDirs } from './fsx.js';
import { mapLimit } from './limit.js';

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
  --concurrency <n>    maximum in-flight file operations (default: 8)
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
      const value = Number(argv[(index += 1)]);
      if (!Number.isInteger(value) || value < 1) throw new Error('--concurrency needs a positive integer');
      opts.concurrency = value;
    } else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  return opts;
}

function firstGroup(match) {
  for (let group = 1; group < match.length; group += 1) {
    if (match[group]) return match[group];
  }
  return '';
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  return `${path.posix.basename(rel, ext)}.${shortHash(bytes)}${ext}`;
}

function sameDeps(prev, next) {
  const left = prev ?? {};
  const right = next ?? {};
  const leftKeys = Object.keys(left);
  if (leftKeys.length !== Object.keys(right).length) return false;
  return leftKeys.every((key) => Object.hasOwn(right, key) && left[key] === right[key]);
}

// The manifest only earns a skip when every output it claims is still on disk:
// a wiped `out/` must rebuild even though no source changed.
async function outputsPresent(outDir, outs) {
  for (const rel of outs) {
    if (!(await pathExists(path.join(outDir, rel)))) return false;
  }
  return true;
}

async function readSources(srcDir, rels) {
  const sources = new Map();
  await mapLimit(rels, DEFAULT_CONCURRENCY, async (rel) => {
    const bytes = await readFile(path.join(srcDir, rel));
    sources.set(rel, { key: contentKey(bytes), bytes, text: isTextSource(rel) ? bytes.toString('utf8') : null });
  });
  return sources;
}

async function readOptional(abs) {
  try {
    return await readFile(abs);
  } catch (error) {
    if (error && error.code === 'ENOENT') return null;
    throw error;
  }
}

// `extends` chains are followed to the root, so a base that itself extends a
// base still contributes its keys before the derived object overrides them.
async function mergeJson(srcDir, rel, stack) {
  if (stack.includes(rel)) throw new Error(`extends cycle: ${[...stack, rel].join(' -> ')}`);
  const own = JSON.parse(await readFile(path.join(srcDir, rel), 'utf8'));
  if (!own || typeof own !== 'object' || Array.isArray(own) || typeof own.extends !== 'string') return own;
  const baseRel = resolveToken(rel, own.extends);
  if (!baseRel) throw new Error(`${rel}: cannot resolve extends "${own.extends}"`);
  const base = await mergeJson(srcDir, baseRel, [...stack, rel]);
  const { extends: dropped, ...rest } = own;
  return { ...base, ...rest };
}

// Returns [output rel path, ...asset rel paths] for one source file. The
// emitted bytes land in `outputs`; nothing here writes to disk.
async function emitSource(ctx, rel) {
  const ext = path.posix.extname(rel).toLowerCase();
  const source = ctx.sources.get(rel);

  if (ext === '.js' || ext === '.mjs') {
    const text = source.text;
    ctx.outputs.set(rel, Buffer.from(`${text.trimEnd()}\n//# build ${shortHash(text)}\n`));
    return [rel];
  }

  if (ext === '.css') {
    const text = source.text;
    const names = new Map();
    const assets = [];
    for (const match of text.matchAll(URL_RE)) {
      const token = firstGroup(match);
      const target = resolveToken(rel, token);
      if (!target) continue;
      const bytes = await readOptional(path.join(ctx.srcDir, target));
      if (!bytes) continue;
      const [, suffix] = splitSuffix(token);
      const name = `${hashedName(target, bytes)}${suffix}`;
      names.set(token, name);
      const outRel = path.posix.join(path.posix.dirname(rel), hashedName(target, bytes));
      ctx.outputs.set(outRel, bytes);
      assets.push(outRel);
    }
    const rewritten = text.replace(URL_RE, (whole, double, single, bare) => {
      const token = double || single || bare || '';
      const name = names.get(token);
      return name ? `url(${name})` : whole;
    });
    ctx.outputs.set(rel, Buffer.from(rewritten));
    return [rel, ...new Set(assets)];
  }

  if (ext === '.json') {
    const merged = await mergeJson(ctx.srcDir, rel, []);
    ctx.outputs.set(rel, Buffer.from(`${JSON.stringify(merged, null, 2)}\n`));
    return [rel];
  }

  ctx.outputs.set(rel, source.bytes);
  return [rel];
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const concurrency = opts.concurrency ?? DEFAULT_CONCURRENCY;
  if (!(await pathExists(srcDir))) {
    throw new Error(`source directory not found: ${path.relative(cwd, srcDir) || srcDir}`);
  }
  const rels = await scanSources(srcDir, [outDir, manifestPath]);
  const sources = await readSources(srcDir, rels);
  const graph = buildDependencyGraph(sources);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };
  const previous = manifest.files ?? {};

  const built = [];
  const skipped = [];
  const dirty = [];
  await mapLimit(rels, concurrency, async (rel) => {
    const source = sources.get(rel);
    const deps = graph.get(rel)?.deps ?? {};
    const prev = previous[rel];
    const reusable =
      prev &&
      prev.key === source.key &&
      sameDeps(prev.deps, deps) &&
      Array.isArray(prev.out) &&
      (await outputsPresent(outDir, prev.out));
    if (reusable) {
      skipped.push(rel);
      return;
    }
    dirty.push(rel);
  });

  const outputs = new Map();
  const nextFiles = {};
  const ctx = { srcDir, sources, outputs };
  for (const rel of [...dirty].sort()) {
    built.push(rel);
    const outs = await emitSource(ctx, rel);
    nextFiles[rel] = { key: sources.get(rel).key, deps: graph.get(rel)?.deps ?? {}, out: outs };
  }
  for (const rel of skipped) {
    nextFiles[rel] = { key: previous[rel].key, deps: previous[rel].deps ?? {}, out: previous[rel].out };
  }

  const nextOut = new Set();
  for (const entry of Object.values(nextFiles)) for (const rel of entry.out) nextOut.add(rel);
  const remove = new Set();
  for (const entry of Object.values(previous)) {
    for (const rel of entry?.out ?? []) {
      if (!nextOut.has(rel) && isInside(outDir, path.join(outDir, rel))) remove.add(rel);
    }
  }

  const removed = Object.keys(previous).filter((rel) => !sources.has(rel)).sort();
  // Keys are written in source order, not in "dirty first" order, so a full
  // build and an incremental build of the same tree produce the same manifest.
  const files = {};
  for (const rel of Object.keys(nextFiles).sort()) {
    files[rel] = { ...nextFiles[rel], out: [...new Set(nextFiles[rel].out)] };
  }
  const next = { version: MANIFEST_VERSION, files };
  return { opts, srcDir, outDir, manifestPath, outputs, remove: [...remove].sort(), removed, built, skipped: skipped.sort(), next };
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

  const writes = [...plan.outputs.entries()].sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
  await mapLimit(writes, opts.concurrency ?? DEFAULT_CONCURRENCY, async ([rel, bytes]) => {
    await writeFileAtomic(path.join(plan.outDir, rel), bytes);
  });
  for (const rel of plan.remove) {
    const abs = path.join(plan.outDir, rel);
    await removeFile(abs);
    await pruneEmptyDirs(plan.outDir, path.dirname(abs));
  }
  // The manifest goes last: an interrupted build never records outputs it did
  // not finish writing.
  await saveManifest(plan.manifestPath, plan.next);
  report.durationMs = Date.now() - started;
  return report;
}
