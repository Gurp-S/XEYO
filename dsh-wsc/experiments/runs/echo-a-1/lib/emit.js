import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { sha1 } from './cache.js';
import { MISSING, resolveDep } from './graph.js';

const URL_RE = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g;

export const HASH_LEN = 8;

// The emitted name of a referenced asset carries the hash of its bytes, so a changed
// asset is a new URL and no client can serve the old bytes under it.
export function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha1(bytes).slice(0, HASH_LEN)}${ext}`;
}

function dirOf(rel) {
  return path.posix.dirname(rel);
}

async function emitModule(rel, text) {
  return [[rel, `${text.trimEnd()}\n//# build ${sha1(text).slice(0, HASH_LEN)}\n`]];
}

// The target asset is emitted next to the stylesheet, so the rewritten url() is the
// emitted file name relative to the stylesheet's own directory.
async function emitStylesheet(rel, srcDir, deps, text) {
  const dir = dirOf(rel);
  const names = new Map();
  const assets = [];
  for (const [target, key] of Object.entries(deps)) {
    if (key === MISSING || names.has(target)) continue;
    const bytes = await readFile(path.join(srcDir, target));
    const name = hashedName(target, bytes);
    names.set(target, name);
    assets.push([path.posix.join(dir, name), bytes]);
  }
  const rewritten = text.replace(URL_RE, (whole, _quote, spec) => {
    const name = names.get(resolveDep(rel, spec));
    return name ? `url(${name})` : whole;
  });
  return [[rel, rewritten], ...assets];
}

async function emitDocument(rel, srcDir, deps, text) {
  const own = JSON.parse(text);
  const { extends: baseSpec, ...rest } = own && typeof own === 'object' ? own : {};
  let merged = rest;
  if (typeof baseSpec === 'string') {
    const baseRel = resolveDep(rel, baseSpec);
    if (baseRel && deps[baseRel] !== MISSING) {
      const base = JSON.parse(await readFile(path.join(srcDir, baseRel), 'utf8'));
      merged = { ...base, ...rest };
    }
  }
  return [[rel, `${JSON.stringify(merged, null, 2)}\n`]];
}

// Renders one source into the output files it produces. Returns `files` (out path ->
// content, the source's own path first) and `out` (the same paths, for the manifest).
export async function emit(rel, { srcDir, deps = {}, bytes }) {
  const ext = path.posix.extname(rel).toLowerCase();
  const content = bytes ?? (await readFile(path.join(srcDir, rel)));
  const text = Buffer.isBuffer(content) ? content.toString('utf8') : String(content);
  let files;
  if (ext === '.js' || ext === '.mjs') files = await emitModule(rel, text);
  else if (ext === '.css') files = await emitStylesheet(rel, srcDir, deps, text);
  else if (ext === '.json') files = await emitDocument(rel, srcDir, deps, text);
  else files = [[rel, content]];
  return { files, out: files.map(([out]) => out) };
}
