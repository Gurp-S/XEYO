import { readdir, readFile, stat, mkdir, writeFile, unlink } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { readDeps, CSS_URL_RE } from './graph.js';
import { contentKey } from './cache.js';
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
  --concurrency <n>    build at most n files at once (default: ${DEFAULT_CONCURRENCY})
  --watch              rebuild whenever the source tree changes
  --dry-run            report the plan without writing anything
  --json               print a machine-readable report
  --help, -h           show this help
`;

const TEXT_EXT = new Set(['.js', '.mjs', '.css', '.json']);

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
      if (raw === undefined || !/^\d+$/.test(raw) || Number(raw) < 1) {
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
    // Symlinks are not followed and not emitted: the builder only owns regular
    // files under the source root.
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

function isText(ext) {
  return TEXT_EXT.has(ext);
}

/**
 * Resolve a JSON `extends` chain. Returns the merged object plus the list of
 * base files it was merged from, so a change anywhere in the chain invalidates
 * the derived file.
 */
function jsonChain(rel, records, seen = new Set()) {
  const record = records.get(rel);
  if (!record || seen.has(rel)) return { merged: {}, chain: [] };
  seen.add(rel);
  let own;
  try {
    own = JSON.parse(record.text);
  } catch {
    return { merged: {}, chain: [] };
  }
  const { extends: spec, ...rest } = own ?? {};
  if (typeof spec !== 'string') return { merged: own, chain: [] };
  const baseRel = resolveDep(rel, spec);
  if (!baseRel || !records.has(baseRel)) return { merged: own, chain: [] };
  const parent = jsonChain(baseRel, records, seen);
  return { merged: { ...parent.merged, ...rest }, chain: [baseRel, ...parent.chain] };
}

/** True when any output recorded for a source is gone from the output tree. */
async function hasMissingOutput(outDir, outList) {
  for (const outRel of outList) {
    try {
      await stat(path.join(outDir, outRel));
    } catch {
      return true;
    }
  }
  return false;
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };
  const prevFiles = manifest.files ?? {};

  // Phase 1: read every source once. Fingerprints are content hashes, so a
  // rewrite that preserves mtime still invalidates the previous build.
  const records = new Map();
  await mapLimit(sources, limit, async (rel) => {
    const bytes = await readFile(path.join(srcDir, rel));
    const ext = path.posix.extname(rel);
    const text = isText(ext) ? bytes.toString('utf8') : null;
    records.set(rel, { rel, ext, bytes, text, key: contentKey(bytes) });
  });

  const keys = new Map();
  for (const [rel, record] of records) keys.set(rel, record.key);

  // Phase 2: fingerprint the dependency graph. A dependency's fingerprint is
  // its content key, so a changed asset invalidates every stylesheet that
  // references it.
  const deps = new Map();
  for (const rel of sources) {
    const record = records.get(rel);
    const resolved = {};
    let specifiers = [];
    try {
      specifiers = await readDeps(path.join(srcDir, rel), record.ext, record.text ?? undefined);
    } catch {
      specifiers = [];
    }
    if (record.ext === '.json') {
      const { chain } = jsonChain(rel, records);
      for (const base of chain) resolved[base] = keys.get(base) ?? 'missing';
    } else {
      for (const spec of specifiers) {
        const target = resolveDep(rel, spec.trim());
        if (!target) continue;
        if (record.ext === '.css' && !records.has(target)) continue;
        resolved[target] = keys.get(target) ?? 'missing';
      }
    }
    deps.set(rel, resolved);
  }

  // Phase 3: decide what is stale. A source is stale when it is new, when its
  // own fingerprint changed, when a recorded dependency changed, or when an
  // output the manifest promises is no longer on disk.
  const dirtyFlags = await mapLimit(sources, limit, async (rel) => {
    const prev = prevFiles[rel];
    if (!prev) return true;
    if (prev.key !== keys.get(rel)) return true;
    const prevDeps = prev.deps ?? {};
    const nextDeps = deps.get(rel) ?? {};
    const depChanged =
      Object.keys(nextDeps).length !== Object.keys(prevDeps).length ||
      Object.entries(nextDeps).some(([dep, key]) => prevDeps[dep] !== key);
    if (depChanged) return true;
    return hasMissingOutput(outDir, Array.isArray(prev.out) && prev.out.length ? prev.out : [rel]);
  });

  const built = [];
  const skipped = [];
  const dirty = [];
  sources.forEach((rel, index) => {
    if (dirtyFlags[index]) {
      built.push(rel);
      dirty.push(rel);
    } else {
      skipped.push(rel);
    }
  });

  // Phase 4: build the stale files, at most `limit` at a time.
  const builtOutputs = new Map(
    await mapLimit(dirty, limit, async (rel) => buildOne(rel, records, deps.get(rel) ?? {})),
  );

  const outputs = new Map();
  for (const [rel, list] of builtOutputs) {
    for (const [outRel, content] of list) {
      if (!outputs.has(outRel)) outputs.set(outRel, content);
    }
  }

  // Phase 5: assemble the next manifest in source order, so the file is
  // byte-for-byte deterministic for a given tree.
  const nextFiles = {};
  for (const rel of sources) {
    const prev = prevFiles[rel];
    const out = builtOutputs.has(rel)
      ? builtOutputs.get(rel).map(([outRel]) => outRel)
      : (prev?.out ?? [rel]);
    nextFiles[rel] = { key: keys.get(rel), deps: deps.get(rel) ?? {}, out };
  }

  const removed = Object.keys(prevFiles).filter((rel) => !(rel in nextFiles));

  // Outputs we produced before and no longer produce: stale assets from a
  // deleted source or a renamed content-hashed asset.
  const previousOut = new Set();
  for (const entry of Object.values(prevFiles)) {
    for (const outRel of entry.out ?? []) previousOut.add(outRel);
  }
  for (const outRel of nextFilesValuesOut(nextFiles)) previousOut.delete(outRel);
  for (const rel of sources) previousOut.delete(rel);
  const obsolete = [...previousOut].filter((outRel) => !outputs.has(outRel)).sort();

  return {
    opts,
    srcDir,
    outDir,
    manifestPath,
    outputs,
    obsolete,
    removed,
    built,
    skipped,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

function* nextFilesValuesOut(files) {
  for (const entry of Object.values(files)) {
    for (const outRel of entry.out ?? []) yield outRel;
  }
}

async function buildOne(rel, records, deps) {
  const record = records.get(rel);
  const list = [];
  if (record.ext === '.js' || record.ext === '.mjs') {
    const text = record.text;
    list.push([rel, `${text.trimEnd()}\n//# build ${sha(text).slice(0, 8)}\n`]);
  } else if (record.ext === '.css') {
    const names = new Map();
    for (const match of record.text.matchAll(CSS_URL_RE)) {
      const target = match[1].trim();
      const relTarget = resolveDep(rel, target);
      const asset = relTarget ? records.get(relTarget) : undefined;
      if (!asset) continue;
      const name = hashedName(relTarget, asset.bytes);
      if (names.has(target)) continue;
      names.set(target, name);
      list.push([path.posix.join(path.posix.dirname(rel), name), asset.bytes]);
    }
    list.push([
      rel,
      record.text.replace(CSS_URL_RE, (whole, target) => `url(${names.get(target.trim()) ?? target})`),
    ]);
  } else if (record.ext === '.json') {
    const { merged } = jsonChain(rel, records);
    list.push([rel, `${JSON.stringify(merged, null, 2)}\n`]);
  } else {
    list.push([rel, record.bytes]);
  }
  return [rel, list];
}

function report(plan, started) {
  return {
    built: plan.built,
    skipped: plan.skipped,
    removed: plan.removed,
    outputs: plan.outputs.size,
    dryRun: Boolean(plan.opts.dryRun),
    durationMs: Date.now() - started,
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  if (opts.dryRun) return report(plan, started);

  await mkdir(plan.outDir, { recursive: true });
  // Outputs first, then the manifest: an interruption can leave the previous
  // manifest describing the previous tree, which the next build heals by
  // noticing missing outputs.
  for (const [outRel, content] of plan.outputs) {
    const abs = path.join(plan.outDir, outRel);
    await mkdir(path.dirname(abs), { recursive: true });
    await writeFile(abs, content);
  }
  for (const outRel of plan.obsolete) {
    await unlink(path.join(plan.outDir, outRel)).catch(() => {});
  }
  await saveManifest(plan.manifestPath, plan.next);
  return report(plan, started);
}
