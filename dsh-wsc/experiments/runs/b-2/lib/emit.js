import path from 'node:path';

import { sha1 } from './cache.js';
import { urlPattern } from './graph.js';
import { hashedName, resolveDep } from './paths.js';

const JS_EXTS = new Set(['.js', '.mjs']);
const TEXT_EXTS = new Set(['.js', '.mjs', '.css', '.json']);

export function isText(rel) {
  return TEXT_EXTS.has(path.posix.extname(rel));
}

function lookupBytes(lookup, rel, spec, from) {
  const bytes = lookup(rel);
  if (!bytes) throw new Error(`missing dependency: ${from} -> ${spec}`);
  return bytes;
}

export function emitJs(text) {
  const trimmed = text.replace(/[ \t]+$/gm, '').replace(/\n+$/, '');
  return `${trimmed}\n//# build ${sha1(text).slice(0, 8)}\n`;
}

export function emitCss(text, rel, lookup) {
  const names = new Map();
  const assets = new Map();
  for (const match of text.matchAll(urlPattern())) {
    const spec = match[2];
    if (names.has(spec)) continue;
    const target = resolveDep(rel, spec);
    if (!target) continue;
    const bytes = lookupBytes(lookup, target, spec, rel);
    const dir = path.posix.dirname(rel);
    const base = hashedName(target, bytes);
    const name = dir === '.' ? base : `${dir}/${base}`;
    names.set(spec, path.posix.relative(dir === '.' ? '.' : dir, name));
    if (!assets.has(name)) assets.set(name, { name, bytes });
  }
  const out = text.replace(urlPattern(), (whole, _quote, spec) => (names.has(spec) ? `url(${names.get(spec)})` : whole));
  return { out, assets: [...assets.values()] };
}

export function emitJson(text, rel, lookup) {
  const own = JSON.parse(text);
  if (!own || typeof own !== 'object' || Array.isArray(own) || typeof own.extends !== 'string') {
    return `${JSON.stringify(own, null, 2)}\n`;
  }
  const baseRel = resolveDep(rel, own.extends);
  if (!baseRel) throw new Error(`invalid extends target: ${rel} -> ${own.extends}`);
  const baseBytes = lookupBytes(lookup, baseRel, own.extends, rel);
  const base = JSON.parse(baseBytes.toString('utf8'));
  const { extends: dropped, ...rest } = own;
  return `${JSON.stringify({ ...base, ...rest }, null, 2)}\n`;
}

// Render one source file into its output files. The primary output keeps the
// source's relative path; a stylesheet also emits the hashed copies of the
// assets its url() rules point at.
export async function emit(rel, bytes, lookup) {
  const ext = path.posix.extname(rel);
  if (JS_EXTS.has(ext)) {
    return { out: [rel], files: [{ name: rel, bytes: emitJs(bytes.toString('utf8')) }] };
  }
  if (ext === '.css') {
    const { out, assets } = emitCss(bytes.toString('utf8'), rel, lookup);
    return { out: [rel, ...assets.map((asset) => asset.name)], files: [{ name: rel, bytes: out }, ...assets] };
  }
  if (ext === '.json') {
    return { out: [rel], files: [{ name: rel, bytes: emitJson(bytes.toString('utf8'), rel, lookup) }] };
  }
  return { out: [rel], files: [{ name: rel, bytes }] };
}
