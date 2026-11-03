// Dependency graph.
//
// Tokens are resolved against the source set: a token that does not name a
// source file is recorded as `missing`, so the file that mentions it rebuilds
// the moment the target appears.

import path from 'node:path';
import { extractDependencies } from './deps.js';

const EXTERNAL_RE = /^(?:[a-z][a-z0-9+.-]*:|\/\/|\/|#)/i;

export function splitSuffix(token) {
  const at = token.search(/[?#]/);
  return at === -1 ? [token, ''] : [token.slice(0, at), token.slice(at)];
}

// Returns the workspace-relative path a token points at, or null when the
// token is not a workspace path at all (URL, data URI, absolute path, anchor).
export function resolveToken(fromRel, token) {
  if (typeof token !== 'string' || token === '') return null;
  const [raw] = splitSuffix(token);
  if (!raw || EXTERNAL_RE.test(raw)) return null;
  const target = path.posix.normalize(path.posix.join(path.posix.dirname(fromRel), raw));
  if (target === '.' || target === '..' || target.startsWith('../')) return null;
  return target;
}

// sources: Map<rel, { text: string | null }>
// Returns Map<rel, { deps: Record<rel, fingerprint|'missing'>, tokens: [{ token, target }] }>
export function buildDependencyGraph(sources) {
  const graph = new Map();
  for (const [rel, source] of sources) {
    const tokens = [];
    if (typeof source.text === 'string') {
      const seen = new Set();
      for (const token of extractDependencies(rel, source.text)) {
        const target = resolveToken(rel, token);
        if (!target || seen.has(`${token}\u0000${target}`)) continue;
        seen.add(`${token}\u0000${target}`);
        tokens.push({ token, target });
      }
    }
    const deps = {};
    for (const { target } of tokens) {
      const dep = sources.get(target);
      deps[target] = dep ? dep.key : 'missing';
    }
    graph.set(rel, { deps, tokens });
  }
  return graph;
}
