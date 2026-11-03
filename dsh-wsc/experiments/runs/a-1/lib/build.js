import { mkdir, readdir, readFile, stat, unlink } from 'node:fs/promises';
import path from 'node:path';
import { extractDeps, isTextSource, URL_RE } from './deps.js';
import { hashBytes } from './cache.js';
import { writeFileAtomic } from './atomic.js';
import { mapLimit } from './concurrency.js';
import { loadManifest, saveManifest, MANIFEST_VERSION } from './manifest.js';

export const DEFAULT_SRC = 'src';
export const DEFAULT_OUT = 'out';
export const DEFAULT_MANIFEST = 'build-manifest.json';
export const DEFAULT_CONCURRENCY = 4;

export const USAGE = `mini-build - build a static asset tree

usage: mini-build [options]

options:
  --src <dir>          source directory (default: ${DEFAULT_SRC})
  --out <dir>          output directory (default: ${DEFAULT_OUT})
  --manifest <file>    manifest file (default: ${DEFAULT_MANIFEST})
  --concurrency <n>    build at most n files at once (default: ${DEFAULT_CONCURRENCY})
  --watch              keep running and rebuild when a source changes
  --dry-run            report what would happen without writing anything
  --json               print the report as JSON
  -h, --help           print this message
`;

function parseConcurrency(value) {
  if (value === undefined || value === '') throw new Error('--concurrency needs a value');
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) throw new Error('--concurrency must be a positive integer');
  return parsed;
}

export function parseArgs(argv) {
  const opts = {
    src: DEFAULT_SRC,
    out: DEFAULT_OUT,
    manifest: DEFAULT_MANIFEST,
    concurrency: DEFAULT_CONCURRENCY,
    dryRun: false,
    json: false,
    watch: false,
    help: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--src') opts.src = argv[(index += 1)];
    else if (arg === '--out') opts.out = argv[(index += 1)];
    else if (arg === '--manifest') opts.manifest = argv[(index += 1)];
    else if (arg === '--concurrency') opts.concurrency = parseConcurrency(argv[(index += 1)]);
    else if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--json') opts.json = true;
    else if (arg === '--watch') opts.watch = true;
    else if (arg === '--help' || arg === '-h') opts.help = true;
    else throw new Error(`unknown argument: ${arg}`);
  }
  for (const key of ['src', 'out', 'manifest']) {
    if (!opts[key]) throw new Error(`--${key} needs a value`);
  }
  return opts;
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

async function walk(dir, base) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    const rel = path.relative(base, abs).split(path.sep).join('/');
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(rel);
  }
  return files.sort();
}

function resolveDep(rel, spec) {
  if (typeof spec !== 'string' || spec === '') return null;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const stem = path.posix.basename(rel, ext);
  return `${stem}.${hashBytes(bytes).slice(0, 8)}${ext}`;
}

// Map a manifest-relative output name to an absolute path, refusing anything
// that would escape the output directory.
function safeOutPath(outDir, rel) {
  if (typeof rel !== 'string' || rel === '' || path.isAbsolute(rel)) return null;
  const abs = path.resolve(outDir, rel);
  const inside = path.relative(outDir, abs);
  if (inside === '' || inside.startsWith('..') || path.isAbsolute(inside)) return null;
  return abs;
}

async function outputsExist(outDir, names) {
  for (const name of names) {
    const abs = safeOutPath(outDir, name);
    if (!abs) return false;
    try {
      await stat(abs);
    } catch {
      return false;
    }
  }
  return true;
}

function parseJson(rel, text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${rel}: invalid JSON (${error instanceof Error ? error.message : String(error)})`);
  }
}

function safeParseJson(text) {
  if (typeof text !== 'string') return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

// Direct and transitive `extends` targets of a JSON source, stopping at the
// first missing or non-JSON base so a broken chain degrades instead of throwing.
function jsonChain(rel, getText) {
  const chain = [];
  const seen = new Set([rel]);
  let current = rel;
  for (;;) {
    const own = safeParseJson(getText(current));
    if (!isPlainObject(own) || typeof own.extends !== 'string') return chain;
    const base = resolveDep(current, own.extends);
    if (!base || seen.has(base)) return chain;
    seen.add(base);
    chain.push(base);
    if (path.posix.extname(base) !== '.json') return chain;
    current = base;
  }
}

function mergeJson(rel, getText, seen = new Set()) {
  const own = parseJson(rel, getText(rel));
  if (!isPlainObject(own) || typeof own.extends !== 'string') return own;
  if (seen.has(rel)) throw new Error(`circular extends: ${[...seen, rel].join(' -> ')}`);
  seen.add(rel);
  const { extends: spec, ...rest } = own;
  const base = resolveDep(rel, spec);
  if (!base || path.posix.extname(base) !== '.json') return rest;
  const baseText = getText(base);
  if (typeof baseText !== 'string') return rest;
  return { ...mergeJson(base, getText, seen), ...rest };
}

export async function planBuild(opts, cwd = process.cwd()) {
  const srcDir = path.resolve(cwd, opts.src);
  const outDir = path.resolve(cwd, opts.out);
  const manifestPath = path.resolve(cwd, opts.manifest);

  const sources = await walk(srcDir, srcDir);
  const manifest = (await loadManifest(manifestPath)) ?? { version: MANIFEST_VERSION, files: {} };
  const prevFiles = manifest.files;

  const bytes = new Map();
  const keys = new Map();
  const texts = new Map();
  for (const rel of sources) {
    const content = await readFile(path.join(srcDir, rel));
    bytes.set(rel, content);
    keys.set(rel, hashBytes(content));
  }
  const getText = (rel) => {
    if (!texts.has(rel)) {
      const content = bytes.get(rel);
      texts.set(rel, content === undefined ? null : content.toString('utf8'));
    }
    return texts.get(rel);
  };

  const deps = new Map();
  for (const rel of sources) {
    const ext = path.posix.extname(rel);
    const resolved = {};
    const add = (target) => {
      if (target && !(target in resolved)) resolved[target] = keys.get(target) ?? 'missing';
    };
    if (isTextSource(ext)) {
      for (const spec of extractDeps(getText(rel) ?? '', ext)) add(resolveDep(rel, spec));
    }
    if (ext === '.json') {
      for (const target of jsonChain(rel, getText)) add(target);
    }
    deps.set(rel, resolved);
  }

  const outputs = new Map();
  const nextFiles = {};
  const built = [];
  const skipped = [];

  for (const rel of sources) {
    const key = keys.get(rel);
    const resolved = deps.get(rel);
    const prev = prevFiles[rel];
    const prevValid =
      isPlainObject(prev) &&
      typeof prev.key === 'string' &&
      isPlainObject(prev.deps) &&
      Array.isArray(prev.out) &&
      prev.out.every((name) => typeof name === 'string');

    const depChanged = !prevValid || Object.entries(resolved).some(([dep, depKey]) => prev.deps[dep] !== depKey);
    const outputMissing = prevValid && !(await outputsExist(outDir, prev.out));

    if (prevValid && prev.key === key && !depChanged && !outputMissing) {
      skipped.push(rel);
      nextFiles[rel] = { key, deps: resolved, out: prev.out };
      continue;
    }

    built.push(rel);
    const ext = path.posix.extname(rel);
    const outNames = [rel];
    if (ext === '.js' || ext === '.mjs') {
      const source = getText(rel) ?? '';
      outputs.set(rel, `${source.trimEnd()}\n//# build ${hashBytes(source).slice(0, 8)}\n`);
    } else if (ext === '.css') {
      const source = getText(rel) ?? '';
      const names = new Map();
      for (const target of extractDeps(source, '.css')) {
        if (names.has(target)) continue;
        const relTarget = resolveDep(rel, target);
        if (!relTarget || !bytes.has(relTarget)) {
          names.set(target, target);
          continue;
        }
        const name = hashedName(relTarget, bytes.get(relTarget));
        names.set(target, name);
        const emitted = path.posix.join(path.posix.dirname(rel), name);
        outputs.set(emitted, bytes.get(relTarget));
        outNames.push(emitted);
      }
      outputs.set(rel, source.replace(URL_RE, (_match, target) => `url(${names.get(target) ?? target})`));
    } else if (ext === '.json') {
      outputs.set(rel, `${JSON.stringify(mergeJson(rel, getText), null, 2)}\n`);
    } else {
      outputs.set(rel, bytes.get(rel));
    }
    nextFiles[rel] = { key, deps: resolved, out: outNames };
  }

  const removed = Object.keys(prevFiles)
    .filter((rel) => !(rel in nextFiles))
    .sort();

  const nextOut = new Set();
  for (const entry of Object.values(nextFiles)) for (const name of entry.out) nextOut.add(name);
  const prevOut = new Set();
  for (const entry of Object.values(prevFiles)) {
    if (!isPlainObject(entry) || !Array.isArray(entry.out)) continue;
    for (const name of entry.out) if (typeof name === 'string') prevOut.add(name);
  }
  const stale = [...prevOut].filter((name) => !nextOut.has(name)).sort();

  return { opts, srcDir, outDir, manifestPath, outputs, removed, stale, built, skipped, next: { version: MANIFEST_VERSION, files: nextFiles } };
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

  await mkdir(plan.outDir, { recursive: true });
  const writes = [...plan.outputs.entries()];
  await mapLimit(writes, opts.concurrency ?? DEFAULT_CONCURRENCY, async ([rel, content]) => {
    const abs = safeOutPath(plan.outDir, rel);
    if (!abs) throw new Error(`refusing to write outside --out: ${rel}`);
    await writeFileAtomic(abs, content);
  });

  for (const rel of plan.stale) {
    const abs = safeOutPath(plan.outDir, rel);
    if (!abs) continue;
    try {
      await unlink(abs);
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }

  await saveManifest(plan.manifestPath, plan.next);

  report.durationMs = Date.now() - started;
  return report;
}

export function formatReport(report, opts = {}) {
  if (opts.json) return `${JSON.stringify(report)}\n`;
  return `built ${report.built.length}, skipped ${report.skipped.length}, removed ${report.removed.length} in ${report.durationMs}ms\n`;
}
