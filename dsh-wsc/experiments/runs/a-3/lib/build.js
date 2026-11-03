import { readdir, readFile, mkdir, rmdir, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { cssUrlTargets, depsFromText, jsonExtendsTarget, resolveDep, URL_RE } from './graph.js';
import { fingerprint, shortFingerprint } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';
import { writeFileAtomic, isTempName } from './atomic.js';
import { DEFAULT_CONCURRENCY, mapLimit, normalizeConcurrency, parseConcurrency } from './pool.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    max files built at once (default: ${DEFAULT_CONCURRENCY})
  --watch              rebuild when a source file changes
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
  return `${base}.${shortFingerprint(bytes)}${ext}`;
}

const TEXT_EXT = new Set(['.js', '.mjs', '.css', '.json']);

function isText(rel) {
  return TEXT_EXT.has(path.posix.extname(rel));
}

function sameOutSet(a, b) {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  for (const item of b) if (!set.has(item)) return false;
  return true;
}

// The `extends` chain of a JSON file, nearest base first, stopping at cycles
// and at bases that are not part of the source tree.
function extendsChain(rel, texts, present) {
  const chain = [];
  const seen = new Set([rel]);
  let current = rel;
  for (;;) {
    const text = texts.get(current);
    if (text === undefined) break;
    const spec = jsonExtendsTarget(text);
    if (!spec) break;
    const target = resolveDep(current, spec);
    if (!target || seen.has(target)) break;
    seen.add(target);
    if (present.has(target)) chain.push(target);
    current = target;
  }
  return chain;
}

// The hashed assets a stylesheet emits beside itself, one per distinct target.
// `name` is the output path, `spec` is the literal `url(...)` argument it
// replaces, so the planner and the rewriter derive both from the same pass.
function cssAssets(rel, text, assets) {
  const found = [];
  const seen = new Set();
  for (const spec of cssUrlTargets(text)) {
    const target = resolveDep(rel, spec);
    if (!target) continue;
    const bytes = assets.get(target);
    if (bytes === undefined) continue;
    const name = path.posix.join(path.posix.dirname(rel), hashedName(target, bytes));
    if (seen.has(name)) continue;
    seen.add(name);
    found.push({ spec, target, name });
  }
  return found;
}

// Every output file a source is expected to produce. The planner and the
// writer both call this, so the recorded `out` list can never drift from what
// the transform actually emits.
function expectedOutputs(rel, text, assets) {
  if (path.posix.extname(rel) !== '.css' || text === undefined) return [rel];
  return [rel, ...cssAssets(rel, text, assets).map((asset) => asset.name)];
}

function mergeJson(rel, texts, present, seen = new Set()) {
  if (seen.has(rel)) return {};
  seen.add(rel);
  const text = texts.get(rel);
  if (text === undefined) return {};
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return parsed;
  const { extends: spec, ...rest } = parsed;
  if (typeof spec !== 'string') return rest;
  const base = resolveDep(rel, spec);
  if (!base || !present.has(base)) return rest;
  return { ...mergeJson(base, texts, present, seen), ...rest };
}

async function exists(file, cache) {
  if (cache.has(file)) return cache.get(file);
  let found = false;
  try {
    found = (await stat(file)).isFile();
  } catch {
    found = false;
  }
  cache.set(file, found);
  return found;
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walk(srcDir, srcDir);
  const manifest = await loadManifest(manifestPath);

  // One read per source: the fingerprint, the dependency scan and the transform
  // all consume the same bytes, so a file that changes mid-build cannot produce
  // an output that disagrees with its recorded key.
  const bytes = new Map();
  const keys = new Map();
  const texts = new Map();
  for (const rel of sources) {
    const buffer = await readFile(path.join(srcDir, rel));
    bytes.set(rel, buffer);
    keys.set(rel, fingerprint(buffer));
    if (isText(rel)) texts.set(rel, buffer.toString('utf8'));
  }
  const present = new Set(sources);

  const deps = new Map();
  for (const rel of sources) {
    const ext = path.posix.extname(rel);
    const text = texts.get(rel);
    const resolved = {};
    if (text !== undefined) {
      for (const { spec } of depsFromText(text, ext)) {
        const target = resolveDep(rel, spec);
        if (target) resolved[target] = null;
      }
      if (ext === '.json') {
        for (const base of extendsChain(rel, texts, present)) resolved[base] = null;
      }
    }
    deps.set(rel, resolved);
  }
  for (const resolved of deps.values()) {
    for (const target of Object.keys(resolved)) resolved[target] = keys.get(target) ?? 'missing';
  }

  const existence = new Map();
  const outputs = new Map();
  const built = [];
  const skipped = [];
  const nextFiles = {};

  for (const rel of sources) {
    const key = keys.get(rel);
    const text = texts.get(rel);
    const resolved = deps.get(rel) ?? {};
    const prev = manifest.files[rel];
    const expected = expectedOutputs(rel, text, bytes);

    const prevDeps = prev?.deps ?? {};
    const depsChanged =
      Object.keys(prevDeps).length !== Object.keys(resolved).length ||
      Object.entries(resolved).some(([dep, depKey]) => prevDeps[dep] !== depKey);
    const outChanged = !prev || !sameOutSet(prev.out ?? [], expected);

    let dirty = !prev || prev.key !== key || depsChanged || outChanged;
    if (!dirty) {
      // A manifest that names an output which is no longer on disk cannot be
      // trusted for this file: rebuild it instead of skipping.
      for (const out of expected) {
        if (!(await exists(path.join(outDir, out), existence))) {
          dirty = true;
          break;
        }
      }
    }

    if (!dirty) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: expected };
      continue;
    }

    built.push(rel);
    const ext = path.posix.extname(rel);
    if (ext === '.js' || ext === '.mjs') {
      outputs.set(rel, `${text.trimEnd()}\n//# build ${shortFingerprint(text)}\n`);
    } else if (ext === '.css') {
      const assets = cssAssets(rel, text, bytes);
      const names = new Map(assets.map((asset) => [asset.spec, asset.name]));
      for (const asset of assets) outputs.set(asset.name, bytes.get(asset.target));
      outputs.set(
        rel,
        text.replace(URL_RE, (whole, spec) => {
          const name = names.get(spec);
          return name ? `url(${name})` : whole;
        }),
      );
    } else if (ext === '.json') {
      outputs.set(rel, `${JSON.stringify(mergeJson(rel, texts, present), null, 2)}\n`);
    } else {
      outputs.set(rel, bytes.get(rel));
    }
    nextFiles[rel] = { key, deps: resolved, out: expected };
  }

  // Outputs recorded by the previous manifest but not produced any more are
  // deleted, otherwise a rebuild would leave stale files (old hashed assets in
  // particular) behind and the tree would stop being a function of the sources.
  const live = new Set();
  for (const entry of Object.values(nextFiles)) for (const out of entry.out) live.add(out);
  const stale = new Set();
  for (const entry of Object.values(manifest.files)) {
    for (const out of entry.out ?? []) {
      if (!live.has(out)) stale.add(out);
    }
  }

  const removed = Object.keys(manifest.files).filter((rel) => !(rel in nextFiles));
  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    stale: [...stale],
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

function insideOut(outDir, rel) {
  const abs = path.resolve(outDir, rel);
  return abs !== outDir && abs.startsWith(outDir + path.sep);
}

async function removeStaleOutputs(plan) {
  const touched = new Set();
  for (const rel of plan.stale) {
    if (!insideOut(plan.outDir, rel)) continue;
    const abs = path.join(plan.outDir, rel);
    if (abs === plan.manifestPath) continue;
    await rm(abs, { force: true });
    touched.add(path.dirname(abs));
  }
  for (const dir of touched) await pruneEmptyDirs(plan.outDir, dir);
}

// Bottom-up removal of directories emptied by the deletions, plus any temp file
// an interrupted build left behind in them.
async function pruneEmptyDirs(outDir, start) {
  let dir = start;
  while (dir.startsWith(outDir + path.sep)) {
    let names;
    try {
      names = await readdir(dir);
    } catch {
      return;
    }
    for (const name of names) {
      if (isTempName(name)) await rm(path.join(dir, name), { force: true });
    }
    if (names.some((name) => !isTempName(name))) return;
    try {
      await rmdir(dir);
    } catch {
      return;
    }
    dir = path.dirname(dir);
  }
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
  const concurrency = normalizeConcurrency(opts.concurrency);
  await mapLimit([...plan.outputs], concurrency, async ([rel, content]) => {
    const abs = path.join(plan.outDir, rel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFileAtomic(abs, content);
  });

  await removeStaleOutputs(plan);

  // The manifest is written last and atomically: it may only ever describe
  // outputs that are already on disk, and a build killed here leaves the
  // previous complete manifest rather than a half-written one.
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
