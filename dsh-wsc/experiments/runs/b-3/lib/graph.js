import { readFile } from 'node:fs/promises';
import path from 'node:path';

const IMPORT_RE = /(?:^|[\s;()])(?:import|export)\s+(?:[^'"();]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const DYNAMIC_RE = /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
const URL_SOURCE = String.raw`url\(\s*(['"]?)([^'")]+)\1\s*\)`;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

function urlMatcher() {
  return new RegExp(URL_SOURCE, 'g');
}

// Remote / root-absolute / fragment-only specifiers are not files in the source tree.
export function isRemoteSpecifier(spec) {
  return /^(?:[a-z][a-z0-9+.-]*:|\/\/|\/|#)/i.test(spec.trim());
}

export function resolveDep(rel, spec) {
  const clean = spec.trim().split(/[?#]/)[0];
  if (!clean || isRemoteSpecifier(clean)) return null;
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(rel), clean));
  if (resolved === '..' || resolved.startsWith('../') || path.posix.isAbsolute(resolved)) return null;
  return resolved;
}

export function collectUrls(text) {
  return [...text.matchAll(urlMatcher())].map((match) => match[2].trim());
}

export function rewriteUrls(text, resolve) {
  return text.replace(urlMatcher(), (whole, quote, target) => {
    const name = resolve(target.trim());
    if (!name) return whole;
    return quote ? `url(${quote}${name}${quote})` : `url(${name})`;
  });
}

// The set of source-relative paths a source file depends on.
export function depSpecifiers(rel, ext, bytes) {
  if (!bytes || bytes.length === 0) return [];
  const text = bytes.toString('utf8');
  if (ext === '.js' || ext === '.mjs') {
    return [...collect(IMPORT_RE, text), ...collect(DYNAMIC_RE, text)].filter((spec) => spec.startsWith('.'));
  }
  if (ext === '.css') return collectUrls(text);
  if (ext === '.json') {
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      return [];
    }
    return data && typeof data === 'object' && typeof data.extends === 'string' ? [data.extends] : [];
  }
  return [];
}

export async function readDeps(abs, ext) {
  const bytes = await readFile(abs);
  return depSpecifiers(path.posix.basename(abs), ext, bytes);
}
