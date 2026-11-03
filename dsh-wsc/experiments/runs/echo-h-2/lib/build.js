import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { stat } from 'node:fs/promises';
import { availableParallelism } from 'node:os';
import path from 'node:path';
import { depsForText } from './graph.js';
import { cacheKey, walkFiles } from './cache.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = Math.max(1, availableParallelism?.() ?? 4);

export const USAGE = `mini-build: incremental build for a small static asset tree

Usage: node bin/build.js [options]

Options:
  --src <dir>          source directory (default: src)
  --out <dir>          output directory (default: out)
  --manifest <file>    build manifest path (default: build-manifest.json)
  --concurrency <n>    build at most n files at once (default: ${DEFAULT_CONCURRENCY})
  --watch              rebuild whenever the source tree changes
  --dry-run            print the plan, write nothing
  --json               print a machine-readable report
  --help, -h           show this message

Sources are content-addressed: a file whose bytes did not change is skipped,
even when its timestamp did. Dependencies are read from JS imports, CSS
url(...) references and JSON \`extends\` chains.
`;

const VALUE_FLAGS = new Set(['src', 'out', 'manifest', 'concurrency']);

function positiveInt(flag, raw) {
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error(`invalid value for ${flag}: ${raw} (expected a positive integer)`);
  }
  return value;
}

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
    if (!arg.startsWith('--') && arg !== '-h') throw new Error(`unknown argument: ${arg}`);
    const body = arg === '-h' ? 'help' : arg.slice(2);
    const eq = body.indexOf('=');
    const name = eq === -1 ? body : body.slice(0, eq);
    const inline = eq === -1 ? undefined : body.slice(eq + 1);

    if (name === 'help') {
      opts.help = true;
    } else if (name === 'watch') {
      opts.watch = true;
    } else if (name === 'dry-run') {
      opts.dryRun = true;
    } else if (name === 'json') {
      opts.json = true;
    } else if (VALUE_FLAGS.has(name)) {
      let value = inline;
      if (value === undefined) {
        index += 1;
        value = argv[index];
        if (value === undefined) throw new Error(`missing value for --${name}`);
      }
      opts[name === 'dry-run' ? 'dryRun' : name] = name === 'concurrency' ? positiveInt(name, value) : value;
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  return opts;
}

const TEXT_EXT = new Set(['.js', '.mjs', '.css', '.json']);
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function short(input) {
  return cacheKey(input).slice('sha1:'.length, 'sha1:'.length + 8);
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${short(bytes)}${ext}`;
}

function resolveDep(rel, spec) {
  if (!spec || /^[a-z]+:/i.test(spec) || spec.startsWith('//')) return null;
  const clean = spec.split(/[?#]/, 1)[0];
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(rel), clean));
  if (resolved.startsWith('..')) return null;
  return resolved;
}

function sameDeps(a = {}, b = {}) {
  const ak = Object.keys(a);
  const bk = Object.keys(b);
  return ak.length === bk.length && ak.every((key) => a[key] === b[key]);
}

// A JSON file's output contains the whole `extends` chain, so every file in the
// chain is a dependency of it.
function extendsTargets(rel, direct) {
  const found = new Set();
  const stack = Object.keys(direct.get(rel) ?? {});
  while (stack.length) {
    const cur = stack.pop();
    if (found.has(cur)) continue;
    found.add(cur);
    stack.push(...Object.keys(direct.get(cur) ?? {}));
  }
  return found;
}

function mergeJson(rel, contents, stack) {
  const own = JSON.parse(contents.get(rel).toString('utf8'));
  if (!own || typeof own !== 'object' || typeof own.extends !== 'string') return own;
  const baseRel = resolveDep(rel, own.extends);
  if (!contents.has(baseRel)) throw new Error(`missing extends target: ${own.extends} (from ${rel})`);
  if (stack.has(baseRel)) throw new Error(`extends cycle: ${rel} -> ${baseRel}`);
  stack.add(rel);
  const base = mergeJson(baseRel, contents, stack);
  stack.delete(rel);
  const { extends: _dropped, ...rest } = own;
  return { ...base, ...rest };
}

async function compile(rel, contents, srcDir) {
  const ext = path.posix.extname(rel);
  const bytes = contents.get(rel);
  if (ext === '.js' || ext === '.mjs') {
    const text = bytes.toString('utf8');
    return { out: [rel], files: [[rel, `${text.trimEnd()}\n//# build ${short(text)}\n`]] };
  }
  if (ext === '.css') {
    const text = bytes.toString('utf8');
    const dir = path.posix.dirname(rel);
    const names = new Map();
    const files = [];
    for (const match of text.matchAll(URL_RE)) {
      const spec = match[1];
      const target = resolveDep(rel, spec);
      if (!target) continue;
      const targetBytes = contents.get(target) ?? (await readFile(path.join(srcDir, target)));
      const name = hashedName(target, targetBytes);
      names.set(spec, name);
      // The asset is emitted next to the stylesheet that references it, so the
      // rewritten url() stays valid wherever the stylesheet sits.
      files.push([path.posix.join(dir, name), targetBytes]);
    }
    files.push([rel, text.replace(URL_RE, (_whole, spec) => `url(${names.get(spec) ?? spec})`)]);
    return { out: files.map(([name]) => name), files };
  }
  if (ext === '.json') {
    const merged = mergeJson(rel, contents, new Set());
    return { out: [rel], files: [[rel, `${JSON.stringify(merged, null, 2)}\n`]] };
  }
  return { out: [rel], files: [[rel, bytes]] };
}

async function missingOutputs(outDir, entry) {
  if (!Array.isArray(entry.out) || entry.out.length === 0) return true;
  for (const name of entry.out) {
    try {
      await stat(path.join(outDir, name));
    } catch {
      return true;
    }
  }
  return false;
}

async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    for (;;) {
      const index = next++;
      if (index >= items.length) return;
      results[index] = await fn(items[index]);
    }
  });
  await Promise.all(workers);
  return results;
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);
  const sources = await walkFiles(srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };
  const previous = manifest.files;

  const contents = new Map();
  const keys = new Map();
  for (const rel of sources) {
    const bytes = await readFile(path.join(srcDir, rel));
    contents.set(rel, bytes);
    keys.set(rel, cacheKey(bytes));
  }

  const direct = new Map();
  for (const rel of sources) {
    const ext = path.posix.extname(rel);
    const resolved = {};
    if (TEXT_EXT.has(ext)) {
      for (const spec of depsForText(ext, contents.get(rel).toString('utf8'))) {
        const target = resolveDep(rel, spec);
        if (target) resolved[target] = true;
      }
    }
    direct.set(rel, resolved);
  }

  const deps = new Map();
  for (const rel of sources) {
    const targets =
      path.posix.extname(rel) === '.json' ? extendsTargets(rel, direct) : new Set(Object.keys(direct.get(rel)));
    const resolved = {};
    for (const target of targets) resolved[target] = keys.get(target) ?? 'missing';
    deps.set(rel, resolved);
  }

  const dirty = [];
  for (const rel of sources) {
    const prev = Object.prototype.hasOwnProperty.call(previous, rel) ? previous[rel] : null;
    const stale =
      !prev ||
      prev.key !== keys.get(rel) ||
      !sameDeps(prev.deps, deps.get(rel)) ||
      (await missingOutputs(outDir, prev));
    if (stale) dirty.push(rel);
  }

  const limit = opts.concurrency ?? DEFAULT_CONCURRENCY;
  const compiled = new Map();
  await mapLimit(dirty, limit, async (rel) => {
    compiled.set(rel, await compile(rel, contents, srcDir));
  });

  const outputs = new Map();
  for (const rel of dirty) for (const [name, bytes] of compiled.get(rel).files) outputs.set(name, bytes);

  const nextFiles = Object.create(null);
  for (const rel of sources) {
    const entry = compiled.get(rel) ?? previous[rel];
    nextFiles[rel] = { key: keys.get(rel), deps: deps.get(rel), out: entry.out };
  }

  const removed = Object.keys(previous).filter((rel) => !(rel in nextFiles));
  const live = new Set();
  for (const rel of Object.keys(nextFiles)) for (const name of nextFiles[rel].out) live.add(name);

  const stale = new Set();
  for (const rel of removed) for (const name of previous[rel].out ?? []) stale.add(name);
  for (const rel of dirty) {
    const fresh = compiled.get(rel).out;
    for (const name of previous[rel]?.out ?? []) if (!fresh.includes(name)) stale.add(name);
  }
  const pruned = [...stale].filter((name) => !live.has(name)).sort();

  return {
    srcDir,
    outDir,
    manifestPath,
    sources,
    dirty,
    skipped: sources.filter((rel) => !compiled.has(rel)),
    removed,
    outputs,
    stale: pruned,
    next: { version: MANIFEST_VERSION, files: nextFiles },
  };
}

export async function build(opts, cwd = process.cwd()) {
  const started = Date.now();
  const plan = await planBuild(opts, cwd);
  if (!opts.dryRun) {
    await mkdir(plan.outDir, { recursive: true });
    for (const [name, bytes] of plan.outputs) {
      const abs = path.join(plan.outDir, name);
      await mkdir(path.dirname(abs), { recursive: true });
      await writeFile(abs, bytes);
    }
    for (const name of plan.stale) await rm(path.join(plan.outDir, name), { force: true });
    await saveManifest(plan.manifestPath, plan.next);
  }
  return {
    dryRun: Boolean(opts.dryRun),
    built: plan.dirty,
    skipped: plan.skipped,
    removed: plan.removed,
    deleted: plan.stale,
    durationMs: Date.now() - started,
  };
}
