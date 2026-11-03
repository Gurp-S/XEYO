import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { urlPattern } from './graph.js';

function sha1(input) {
  return createHash('sha1').update(input).digest('hex');
}

/**
 * Turn a specifier into the source-relative path it points at, or null when it
 * is not a source file of this tree (remote url, data: uri, absolute path,
 * bare module id, in-document fragment).
 */
export function resolveDep(rel, spec) {
  const trimmed = typeof spec === 'string' ? spec.trim() : '';
  if (!trimmed) return null;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(trimmed)) return null;
  const clean = trimmed.split(/[?#]/)[0];
  if (!clean) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), clean));
}

/** `basename.<sha1-of-bytes first 8 hex>.ext`, emitted next to the stylesheet. */
function assetName(relTarget, bytes) {
  const dir = path.posix.dirname(relTarget);
  const base = path.posix.basename(relTarget);
  const ext = path.posix.extname(base);
  const stem = ext ? base.slice(0, -ext.length) : base;
  const name = `${stem}.${sha1(bytes).slice(0, 8)}${ext}`;
  return dir === '.' ? name : path.posix.join(dir, name);
}

async function emitCss(srcDir, rel) {
  const text = await readFile(path.join(srcDir, rel), 'utf8');
  const names = new Map();
  const assets = [];
  for (const match of text.matchAll(urlPattern())) {
    const target = match[1];
    if (names.has(target)) continue;
    const relTarget = resolveDep(rel, target);
    if (!relTarget) continue;
    const bytes = await readFile(path.join(srcDir, relTarget));
    const name = assetName(relTarget, bytes);
    names.set(target, name);
    if (!assets.some(([outRel]) => outRel === name)) assets.push([name, bytes]);
  }
  const css = text.replace(urlPattern(), (whole, target) => (names.has(target) ? `url(${names.get(target)})` : whole));
  return [[rel, css], ...assets];
}

async function emitJson(srcDir, rel) {
  const own = JSON.parse(await readFile(path.join(srcDir, rel), 'utf8'));
  let merged = own;
  if (own && typeof own.extends === 'string') {
    const relBase = resolveDep(rel, own.extends);
    const base = JSON.parse(await readFile(path.join(srcDir, relBase), 'utf8'));
    const { extends: _dropped, ...rest } = own;
    merged = { ...base, ...rest };
  }
  return [[rel, `${JSON.stringify(merged, null, 2)}\n`]];
}

async function emitJs(srcDir, rel) {
  const text = await readFile(path.join(srcDir, rel), 'utf8');
  return [[rel, `${text.trimEnd()}\n//# build ${sha1(text).slice(0, 8)}\n`]];
}

/**
 * Compile one source into the list of `[outRel, content]` pairs it produces.
 * Every output is a pure function of the source bytes and, for stylesheets and
 * JSON, of the bytes of the files they pull in.
 */
export async function emitSource(srcDir, rel) {
  const ext = path.posix.extname(rel);
  if (ext === '.css') return emitCss(srcDir, rel);
  if (ext === '.json') return emitJson(srcDir, rel);
  return emitJs(srcDir, rel);
}
