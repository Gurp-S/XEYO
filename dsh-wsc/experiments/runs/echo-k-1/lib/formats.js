import path from 'node:path';
import { sha1 } from './fingerprint.js';

// One entry per source format. Each entry answers two questions and nothing
// else: which other sources does this text name (its dependency specifiers),
// and what output bytes does it become. A format that references other sources
// has to be registered here, otherwise its dependencies stay invisible to the
// incremental planner and its output can never go stale.

const JS_IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const CSS_URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function captures(re, text) {
  return [...text.matchAll(re)].map((match) => match[1]);
}

function jsSpecifiers(text) {
  return captures(JS_IMPORT_RE, text);
}

function cssSpecifiers(text) {
  return captures(CSS_URL_RE, text);
}

function jsonSpecifiers(text) {
  const own = parseJson(text);
  return own && typeof own.extends === 'string' ? [own.extends] : [];
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`invalid JSON: ${error.message}`);
  }
}

// Content-addressed asset names: the name is a function of the bytes, so a
// changed asset cannot be served under its previous name.
export function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha1(bytes).slice(0, 8)}${ext}`;
}

function emitScript({ rel, text }) {
  return {
    out: [rel],
    contents: new Map([[rel, `${text.trimEnd()}\n//# build ${sha1(text).slice(0, 8)}\n`]]),
  };
}

function emitStylesheet({ rel, text, resolve, source }) {
  const contents = new Map();
  const out = [rel];
  const names = new Map();
  for (const target of captures(CSS_URL_RE, text)) {
    const dep = resolve(target);
    const asset = dep ? source(dep) : null;
    // External, absolute, or not part of the tree: there is nothing to hash, so
    // the url is left exactly as written.
    if (!asset) continue;
    const name = hashedName(dep, asset.bytes);
    names.set(target, name);
    contents.set(name, asset.bytes);
    if (!out.includes(name)) out.push(name);
  }
  contents.set(rel, text.replace(CSS_URL_RE, (whole, target) => `url(${names.get(target) ?? target})`));
  return { out, contents };
}

function emitJson({ rel, text, resolve, source }) {
  const own = parseJson(text);
  let merged = own;
  if (own && typeof own.extends === 'string') {
    const baseRel = resolve(own.extends);
    const base = baseRel ? source(baseRel) : null;
    if (!base) throw new Error(`${rel}: extends target not found: ${own.extends}`);
    const rest = { ...own };
    delete rest.extends;
    merged = { ...parseJson(base.text), ...rest };
  }
  return { out: [rel], contents: new Map([[rel, `${JSON.stringify(merged, null, 2)}\n`]]) };
}

function emitCopy({ rel, bytes }) {
  return { out: [rel], contents: new Map([[rel, bytes]]) };
}

const FORMATS = new Map([
  ['.js', { specifiers: jsSpecifiers, emit: emitScript }],
  ['.mjs', { specifiers: jsSpecifiers, emit: emitScript }],
  ['.css', { specifiers: cssSpecifiers, emit: emitStylesheet }],
  ['.json', { specifiers: jsonSpecifiers, emit: emitJson }],
]);

const COPY = { specifiers: () => [], emit: emitCopy };

export function formatFor(ext) {
  return FORMATS.get(ext) ?? COPY;
}

export function isTextFormat(ext) {
  return FORMATS.has(ext);
}
