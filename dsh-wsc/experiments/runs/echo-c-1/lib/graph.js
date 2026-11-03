import path from 'node:path';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  re.lastIndex = 0;
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

// Every reference a source makes to another source, whatever the format: an
// import in JS, a url(...) in CSS, an extends in JSON. A file is rebuilt when
// any of these targets changes, so they are recorded as manifest dependencies.
export function dependencySpecifiers(rel, bytes) {
  const ext = path.posix.extname(rel);
  const text = bytes.toString('utf8');
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  if (ext === '.json') {
    try {
      const own = JSON.parse(text);
      return own && typeof own.extends === 'string' ? [own.extends] : [];
    } catch {
      return [];
    }
  }
  return [];
}

export function resolveDep(rel, spec) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

export { URL_RE };
