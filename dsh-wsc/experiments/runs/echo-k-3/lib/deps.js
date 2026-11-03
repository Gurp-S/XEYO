// Dependency extraction.
//
// Every extractor returns the raw strings a source file mentions that might
// name another file. Resolving a token to a workspace path needs the whole
// source set, so nothing here touches the disk.

const URL_RE = /url\(\s*(?:"([^"]*)"|'([^']*)'|([^)'"\s]+))\s*\)/g;
const CSS_IMPORT_RE = /@import\s+(?:"([^"]+)"|'([^']+)')/g;
const JS_STATIC_RE = /(?:^|[\s;{}()])(?:import|export)\s+(?:[^'";]*?\bfrom\s*)?["']([^"']+)["']/g;
const JS_DYNAMIC_RE = /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g;
const JSON_EXTENDS_RE = /"extends"\s*:\s*"([^"]+)"/g;

const TEXT_EXTENSIONS = new Set(['css', 'js', 'mjs', 'cjs', 'json']);

function extensionOf(rel) {
  const dot = rel.lastIndexOf('.');
  return dot === -1 ? '' : rel.slice(dot + 1).toLowerCase();
}

function collect(re, text) {
  const found = [];
  re.lastIndex = 0;
  let match;
  while ((match = re.exec(text)) !== null) {
    for (let group = 1; group < match.length; group += 1) {
      if (match[group]) {
        found.push(match[group]);
        break;
      }
    }
  }
  return found;
}

export function isTextSource(rel) {
  return TEXT_EXTENSIONS.has(extensionOf(rel));
}

export function extractDependencies(rel, text) {
  const ext = extensionOf(rel);
  if (ext === 'css') {
    return [...collect(URL_RE, text), ...collect(CSS_IMPORT_RE, text)];
  }
  if (ext === 'js' || ext === 'mjs' || ext === 'cjs') {
    return [...collect(JS_STATIC_RE, text), ...collect(JS_DYNAMIC_RE, text)];
  }
  if (ext === 'json') {
    // A derived config names its base file; the base must rebuild the derived
    // file even when the derived file itself was not touched.
    return collect(JSON_EXTENDS_RE, text);
  }
  return [];
}

export { extensionOf, URL_RE };
