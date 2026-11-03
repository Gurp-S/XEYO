const URL_RE = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g;

export function urlTargets(text) {
  const targets = [];
  for (const match of text.matchAll(URL_RE)) targets.push(match[2]);
  return targets;
}

// `resolve` returns the replacement target or null to leave the url() untouched.
export function rewriteUrls(text, resolve) {
  return text.replace(URL_RE, (whole, quote, target) => {
    const replacement = resolve(target);
    return replacement == null ? whole : `url(${replacement})`;
  });
}
