// Every edge a source can have to another source lives here: static imports and
// re-exports in scripts, url() targets in stylesheets, extends in json. The
// planner turns these specifiers into recorded dependencies so a change to a
// referenced file rebuilds the referrer.
const IMPORT_RE = /(?:^|[^.\w$])import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const EXPORT_RE = /(?:^|[^.\w$])export\s+[^'"\n]*?\s+from\s+['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

export function readDeps(text, ext) {
  if (ext === '.js' || ext === '.mjs') {
    return [...collect(IMPORT_RE, text), ...collect(EXPORT_RE, text)];
  }
  if (ext === '.css') return collect(URL_RE, text);
  if (ext === '.json') {
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === 'object' && typeof parsed.extends === 'string'
        ? [parsed.extends]
        : [];
    } catch {
      return [];
    }
  }
  return [];
}
