import { readdir, readFile, stat, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { depsOf, isTextExt } from './graph.js';
import { fingerprint, shortHash } from './cache.js';
import { rewriteUrls, urlSpecifiers } from './css.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { writeFileAtomic } from './atomic.js';
import { reapOutputs } from './outputs.js';
import { mapLimit } from './pool.js';
import { watchSources } from './watch.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 8;

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>        source directory (default: src)
  --out <dir>        output directory (default: out)
  --manifest <file>  build manifest path (default: build-manifest.json)
  --concurrency <n>  build at most n files at once (default: 8)
  --watch            keep running and rebuild when a source changes
  --dry-run          report the plan without writing anything
  --json             print a machine-readable report
  --help, -h         show this help
`;

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
    else if (arg === '--concurrency') opts.concurrency = argv[(index += 1)];
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  const raw = opts.concurrency;
  const concurrency = typeof raw === 'number' ? raw : Number(raw);
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

function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

// `url(img.png?v=1#frag)` names a file by its path part only; the query and
// fragment are the referrer's business and never reach the filesystem.
function resolveSpec(rel, spec) {
  const clean = spec.split('#')[0].split('?')[0];
  if (!clean) return null;
  return resolveDep(rel, clean);
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${shortHash(bytes)}${ext}`;
}

function outAbs(outDir, rel) {
  return path.join(outDir, ...rel.split('/'));
}

// A manifest entry is only a claim; the bytes it names have to be there too,
// otherwise a stale manifest would keep a missing output missing forever.
async function missingOutputs(outDir, prev) {
  if (!prev || !Array.isArray(prev.out) || prev.out.length === 0) return true;
  for (const rel of prev.out) {
    try {
      if (!(await stat(outAbs(outDir, rel))).isFile()) return true;
    } catch {
      return true;
    }
  }
  return false;
}

async function scanSources(srcDir, sources, concurrency) {
  const keys = new Map();
  const specs = new Map();
  const scanned = await mapLimit(sources, concurrency, async (rel) => {
    const abs = path.join(srcDir, rel);
    const ext = path.posix.extname(rel);
    if (!isTextExt(ext)) return { rel, key: fingerprint(await readFile(abs)), specs: [] };
    const text = await readFile(abs, 'utf8');
    return { rel, key: fingerprint(text), specs: depsOf(text, ext) };
  });
  for (const item of scanned) {
    keys.set(item.rel, item.key);
    specs.set(item.rel, item.specs);
  }
  return { keys, specs };
}

function parseJson(text, label) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${label}: invalid JSON (${error instanceof Error ? error.message : String(error)})`);
  }
}

const isPlainObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);

// Build one source into the outputs it claims. Entries are returned rather
// than written so the caller keeps a deterministic write order.
async function buildOne(rel, srcDir) {
  const ext = path.posix.extname(rel);
  const abs = path.join(srcDir, rel);
  const out = [rel];
  const assets = [];

  let body;
  if (ext === '.js' || ext === '.mjs') {
    const text = await readFile(abs, 'utf8');
    body = `${text.trimEnd()}\n//# build ${shortHash(text)}\n`;
  } else if (ext === '.css') {
    const text = await readFile(abs, 'utf8');
    const names = new Map();
    for (const target of urlSpecifiers(text)) {
      const source = resolveSpec(rel, target);
      if (!source) continue;
      let bytes;
      try {
        bytes = await readFile(path.join(srcDir, ...source.split('/')));
      } catch {
        // The stylesheet points at nothing this tree can emit; leave the
        // reference exactly as the author wrote it.
        continue;
      }
      const name = hashedName(source, bytes);
      names.set(target, name);
      assets.push([name, bytes]);
      out.push(name);
    }
    body = rewriteUrls(text, names);
  } else if (ext === '.json') {
    const own = parseJson(await readFile(abs, 'utf8'), rel);
    let merged = own;
    if (isPlainObject(own) && typeof own.extends === 'string') {
      const baseRel = resolveSpec(rel, own.extends);
      let base = {};
      if (baseRel) {
        let baseText;
        try {
          baseText = await readFile(path.join(srcDir, ...baseRel.split('/')), 'utf8');
        } catch {
          throw new Error(`${rel}: extends target not found: ${own.extends}`);
        }
        base = parseJson(baseText, `${rel} -> ${baseRel}`);
      }
      const { extends: dropped, ...rest } = own;
      merged = { ...(isPlainObject(base) ? base : {}), ...rest };
    }
    body = `${JSON.stringify(merged, null, 2)}\n`;
  } else {
    body = await readFile(abs);
  }

  return { out, entries: [[rel, body], ...assets] };
}

export async function planBuild(opts, cwd = process.cwd()) {
  const concurrency = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };

  const { keys, specs } = await scanSources(srcDir, sources, concurrency);

  const deps = new Map();
  for (const rel of sources) {
    const resolved = {};
    for (const spec of specs.get(rel) ?? []) {
      const target = resolveSpec(rel, spec);
      if (target) resolved[target] = null;
    }
    deps.set(rel, resolved);
  }
  for (const resolved of deps.values()) {
    for (const target of Object.keys(resolved)) resolved[target] = keys.get(target) ?? 'missing';
  }

  const decisions = await mapLimit(sources, concurrency, async (rel) => {
    const key = keys.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const stale = Object.entries(resolved).some(([dep, depKey]) => (prev?.deps ?? {})[dep] !== depKey);
    const dirty = !prev || prev.key !== key || stale || (await missingOutputs(outDir, prev));
    if (!dirty) return { rel, dirty, key, resolved, out: prev.out ?? [rel], entries: [] };
    const built = await buildOne(rel, srcDir);
    return { rel, dirty, key, resolved, out: built.out, entries: built.entries };
  });

  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};
  for (const decision of decisions) {
    if (decision.dirty) {
      built.push(decision.rel);
      for (const [name, content] of decision.entries) outputs.set(name, content);
    } else {
      skipped.push(decision.rel);
    }
    nextFiles[decision.rel] = { key: decision.key, deps: decision.resolved, out: decision.out };
  }

  const claimed = new Set();
  for (const entry of Object.values(nextFiles)) for (const name of entry.out) claimed.add(name);

  const previous = new Set();
  for (const [rel, entry] of Object.entries(manifest.files)) {
    for (const name of Array.isArray(entry?.out) ? entry.out : [rel]) previous.add(name);
  }
  const removed = [...previous].filter((name) => !claimed.has(name)).sort();

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    claimed,
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  const summary = {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun: Boolean(opts.dryRun),
  };
  if (opts.dryRun) return { ...summary, durationMs: Date.now() - started };

  await mkdir(plan.outDir, { recursive: true });
  for (const [rel, content] of plan.outputs) {
    await writeFileAtomic(outAbs(plan.outDir, rel), content);
  }
  const reaped = await reapOutputs(plan.outDir, plan.claimed, new Set([plan.manifestPath]));
  // The manifest is the commit point: it is written last and atomically, so an
  // interrupted build leaves the previous manifest intact.
  await saveManifest(plan.manifestPath, plan.next);
  return { ...summary, removed: reaped, durationMs: Date.now() - started };
}

export async function watch(opts, cwd = process.cwd(), onReport = () => {}) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const run = async () => {
    try {
      onReport(await build({ ...opts, dryRun: false }, cwd));
    } catch (error) {
      onReport({ error: error instanceof Error ? error.message : String(error) });
    }
  };
  await run();
  return watchSources(srcDir, run, { ignore: outDir });
}
